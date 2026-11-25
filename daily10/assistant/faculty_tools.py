"""
Faculty Copilot tools. Read tools run straight away; anything that changes what students see,
or spends LLM budget in bulk, waits for the faculty member's approval in the chat.

Two tools hand work to specialist sub-agents (subagents.py): review_question runs the reviewer on a
different model family from the one that wrote the questions; draft_questions runs the writer.
"""

from typing import Literal

from pydantic import BaseModel, Field

from daily10 import insights, service
from daily10.assistant import subagents
from daily10.assistant.registry import Context, tool

F = {"faculty"}


class SubjectArg(BaseModel):
    subject: str = Field(description="Subject code, e.g. CC701")


@tool("list_subjects", F, label=lambda a: "Listing subjects")
def list_subjects(ctx: Context, a) -> dict:
    """Every subject with its code, name, department, semester and number of topics."""
    return {"subjects": service.list_subjects()}


@tool("subject_overview", F, SubjectArg, label=lambda a: f"Opening {a.subject.upper()}")
def subject_overview(ctx: Context, a: SubjectArg) -> dict:
    """A subject at a glance: topics in syllabus order with exam weight (times asked in past papers)
    and question counts, the review queue (drafts, flagged/reported, not AI-checked), students enrolled."""
    ov = insights.subject_overview(a.subject)
    ov["topic_list"] = [{k: t[k] for k in ("id", "position", "title", "exam_weight", "questions")} for t in ov["topic_list"]]
    return ov


class ListQuestionsArgs(BaseModel):
    subject: str
    status: Literal["draft", "approved", "rejected", "auto_rejected"] | None = None
    flagged_only: bool = Field(False, description="Only questions the AI check flagged or students reported")
    topic_id: int | None = None
    limit: int = Field(10, ge=1, le=25)


@tool("list_questions", F, ListQuestionsArgs,
      label=lambda a: f"Listing {'flagged ' if a.flagged_only else ''}{a.status or ''} questions in {a.subject.upper()}".replace("  ", " "))
def list_questions(ctx: Context, a: ListQuestionsArgs) -> dict:
    """Questions with their marked answer and review status; flagged and reported ones first."""
    rows = insights.filter_questions(service.list_questions(a.subject, a.status), a.flagged_only, a.topic_id)
    keep = ("id", "topic_id", "topic", "prompt", "options", "answer_index", "level", "status", "status_reason", "reports")
    return {"total": len(rows), "questions": [{k: q[k] for k in keep} | {"evidence": q["evidence"][:200]}
                                              for q in rows[:a.limit]]}


class QuestionArg(BaseModel):
    question_id: int


@tool("get_question", F, QuestionArg, label=lambda a: f"Opening question {a.question_id}")
def get_question(ctx: Context, a: QuestionArg) -> dict:
    """One question in full: options, marked answer, evidence quote, status and reason, student
    reports, automatic check results and how students have answered it."""
    return insights.question_detail(a.question_id)


@tool("class_insights", F, SubjectArg, label=lambda a: f"Analysing the {a.subject.upper()} class")
def class_insights(ctx: Context, a: SubjectArg) -> dict:
    """How the class is doing: coverage, accuracy, students behind schedule or inactive, weakest
    topics, hardest questions, reported questions, per-student and per-topic numbers."""
    out = insights.class_insights(a.subject)
    out["students"] = out["students"][:20]
    return out


@tool("review_question", F, QuestionArg,
      label=lambda a: f"Reviewer agent checking question {a.question_id} against the notes")
def review_question(ctx: Context, a: QuestionArg) -> dict:
    """Hand one question to the independent reviewer agent (a different model family). It searches
    the notes and returns approve / reject / edit with cited reasons and, if fixable, a suggested edit
    with verified evidence. Changes nothing by itself."""
    return subagents.review_question(a.question_id, ctx).model_dump()


class DraftArgs(BaseModel):
    subject: str
    focus: str = Field(description="What to test, e.g. a weak topic or a concept often asked in exams")
    n: int = Field(3, ge=1, le=5)


@tool("draft_questions", F, DraftArgs, label=lambda a: f"Writer agent drafting {a.n} questions on “{a.focus}”")
def draft_questions(ctx: Context, a: DraftArgs) -> dict:
    """Hand a focus area to the writer agent: it finds the right notes and writes new questions.
    Grounded ones are saved as DRAFTS (students don't see them until approved)."""
    return subagents.draft_questions(a.subject, a.focus, a.n, ctx).model_dump()


class StatusArgs(BaseModel):
    question_ids: list[int] = Field(min_length=1, max_length=25)
    status: Literal["approved", "rejected", "draft"]
    reason: str = Field("", max_length=300)


def _status_summary(a: StatusArgs) -> str:
    verb = {"approved": "Approve", "rejected": "Reject", "draft": "Send back to draft"}[a.status]
    ids = ", ".join(f"#{i}" for i in a.question_ids)
    n = len(a.question_ids)
    return f"{verb} {n} question{'s' if n > 1 else ''}: {ids}" + (f" (reason: {a.reason})" if a.reason else "")


@tool("set_question_status", F, StatusArgs, confirm=True, summary=_status_summary,
      label=lambda a: f"Setting {len(a.question_ids)} question(s) to {a.status}")
def set_question_status(ctx: Context, a: StatusArgs) -> dict:
    """Approve, reject or send back to draft one or more questions. Only approved questions reach
    students. Needs the faculty member's approval in the chat."""
    note = a.reason.strip() or ("" if a.status == "approved" else f"{a.status} by {ctx.actor} via assistant")
    done, errors = [], {}
    for qid in a.question_ids:
        try:
            service.set_question_status(qid, a.status, note)
            done.append(qid)
        except service.NotFound as e:
            errors[qid] = str(e)
    return {"status": a.status, "updated": done, "errors": errors}


class EditArgs(BaseModel):
    question_id: int
    prompt: str | None = None
    options: list[str] | None = Field(None, description="Exactly 4 distinct options")
    answer_index: int | None = Field(None, ge=0, le=3)
    explanation: str | None = None
    evidence: str | None = Field(None, description="Word-for-word quote from the topic's notes")


@tool("edit_question", F, EditArgs, confirm=True, label=lambda a: f"Editing question {a.question_id}",
      summary=lambda a: f"Edit question #{a.question_id}: " + ", ".join(
          k for k in ("prompt", "options", "answer_index", "explanation", "evidence") if getattr(a, k) is not None))
def edit_question(ctx: Context, a: EditArgs) -> dict:
    """Change a question (e.g. a reviewer's suggested edit). Evidence must quote the topic's notes
    word for word. The question goes back to draft for approval."""
    changes = a.model_dump(exclude={"question_id"})
    return service.edit_question(a.question_id, changes, editor=f"{ctx.actor} via assistant")


class GenerateArgs(BaseModel):
    subject: str
    limit: int = Field(3, ge=1, le=5, description="Topics to process now (free LLM tiers have daily limits)")


@tool("generate_questions", F, GenerateArgs, confirm=True,
      label=lambda a: f"Generating summaries and questions for {a.limit} {a.subject.upper()} topics",
      summary=lambda a: f"Generate summaries and draft questions for up to {a.limit} {a.subject.upper()} topics (uses LLM quota)")
def generate_questions(ctx: Context, a: GenerateArgs) -> dict:
    """Write titles, summaries and draft questions for topics that don't have them yet."""
    return service.generate_questions(a.subject, ctx.llm(), True, a.limit)


@tool("run_ai_check", F, SubjectArg, confirm=True, label=lambda a: f"Running the AI check on {a.subject.upper()} drafts",
      summary=lambda a: f"Run the independent AI check on unchecked {a.subject.upper()} drafts (uses LLM quota)")
def run_ai_check(ctx: Context, a: SubjectArg) -> dict:
    """A different model answers each unchecked draft blind from the notes; disagreements are flagged."""
    return service.check_questions(a.subject, ctx.llm("judge"))


class CreateSubjectArgs(BaseModel):
    code: str = Field(min_length=2, max_length=32)
    name: str = Field(min_length=2, max_length=200)
    department: str = ""
    semester: int = Field(0, ge=0, le=12)


@tool("create_subject", F, CreateSubjectArgs, confirm=True, label=lambda a: f"Creating {a.code.upper()}",
      summary=lambda a: f"Create subject {a.code.upper()} “{a.name}”")
def create_subject(ctx: Context, a: CreateSubjectArgs) -> dict:
    """Create a new subject. Notes are uploaded on the subject's Upload page."""
    try:
        service.get_subject(a.code)
        raise ValueError(f"{a.code.upper()} already exists.")
    except service.NotFound:
        s = service.create_subject(a.code, a.name, a.department, a.semester)
    return {"code": s.code, "name": s.name, "upload_page": f"/faculty/{s.code}/upload"}
