"""
Study Buddy tools: what a signed-in student can do through the assistant. Every tool acts as
that student only, and searches only their enrolled subjects.

Quizzes never show the model the answer: quiz_me returns the question without it, and only
check_answer (after the student has chosen) reveals it and records the attempt for spaced repetition.
"""

import re
from datetime import date
from typing import Literal

from pydantic import BaseModel, Field, field_validator
from sqlalchemy import func, select

from daily10 import config, db, scheduler, service
from daily10.assistant.registry import Context, tool
from daily10.db import Enrollment, Question, Review, Subject, Topic, TopicProgress

S = {"student"}
LETTERS = "ABCD"


def _student(ctx: Context):
    return service.get_student(ctx.student_code)


def enrolled_subjects(student_code: str) -> dict[str, dict]:
    student = service.get_student(student_code)
    with db.session() as s:
        rows = s.execute(select(Enrollment, Subject).join(Subject).where(Enrollment.student_id == student.id)).all()
        return {sub.code: {"id": sub.id, "name": sub.name, "exam_date": e.exam_date, "start_date": e.start_date}
                for e, sub in rows}


@tool("my_overview", S, label=lambda a: "Looking at your progress")
def my_overview(ctx: Context, a) -> dict:
    """The student's subjects and exam dates, syllabus coverage, streak, accuracy, weakest topics,
    and reminder settings."""
    profile = service.student_profile(ctx.student_code)
    return {**service.progress(ctx.student_code), "reminder_time": profile["notify_time"],
            "telegram_linked": profile["telegram_linked"], "today": config.local_today().isoformat()}


@tool("get_today", S, label=lambda a: "Opening today's session")
def get_today(ctx: Context, a) -> dict:
    """Today's 10-minute session: the concept card (topic summary and key points), the questions
    due today (not their answers), and the past exam question."""
    session = service.today_session(ctx.student_code)
    return {k: session[k] for k in ("day", "card", "past_question", "notes", "completed")} | {
        "questions": [{"question_id": q["id"], "kind": q["kind"], "topic": q["topic"], "answered": q["answered"]}
                      for q in session["questions"]]}


class SubjectArg(BaseModel):
    subject: str = Field(description="Subject code, e.g. CC701")


@tool("study_plan", S, SubjectArg, label=lambda a: f"Working out your {a.subject.upper()} schedule")
def study_plan(ctx: Context, a: SubjectArg) -> dict:
    """Is the student on track for this exam? Topics left, days until revision starts, the pace
    needed, upcoming topics, the most-examined topics still to learn, and reviews due."""
    code = a.subject.strip().upper()
    subjects = enrolled_subjects(ctx.student_code)
    if code not in subjects:
        raise PermissionError(f"{code} isn't one of your subjects.")
    info, today, student = subjects[code], config.local_today(), _student(ctx)
    with db.session() as s:
        topics = s.scalars(select(Topic).where(Topic.subject_id == info["id"]).order_by(Topic.position)).all()
        learned = set(s.scalars(select(TopicProgress.topic_id).where(TopicProgress.student_id == student.id)))
        due = s.scalar(select(func.count()).select_from(Review).join(Question).join(Topic).where(
            Review.student_id == student.id, Review.due_on <= today, Topic.subject_id == info["id"]))
    plan = scheduler.SubjectPlan(info["id"], info["exam_date"], info["start_date"], [t.id for t in topics], learned)
    needed_today, left = scheduler.topics_due_today(plan, today)
    revision = scheduler.revision_start(info["start_date"], info["exam_date"])
    days_to_revision = max((revision - today).days + 1, 0)
    remaining = [t for t in topics if t.id not in learned]
    return {
        "subject": code, "name": info["name"], "today": today.isoformat(), "exam_date": info["exam_date"].isoformat(),
        "days_to_exam": (info["exam_date"] - today).days, "revision_starts": revision.isoformat(),
        "topics_total": len(topics), "topics_left": left, "new_topics_today": needed_today,
        "pace_needed_per_day": round(left / days_to_revision, 2) if days_to_revision else None,
        "max_new_topics_per_day": scheduler.MAX_NEW_PER_DAY, "on_track": not scheduler.is_behind(plan, today),
        "reviews_due": due,
        "next_topics": [{"topic_id": t.id, "title": t.title or t.source, "exam_weight": t.exam_weight} for t in remaining[:5]],
        "most_examined_left": [{"topic_id": t.id, "title": t.title or t.source, "exam_weight": t.exam_weight}
                               for t in sorted(remaining, key=lambda t: -t.exam_weight)[:3] if t.exam_weight],
    }


@tool("browse_subjects", S, label=lambda a: "Listing subjects you can add")
def list_subjects(ctx: Context, a) -> dict:
    """Every subject the college offers in Daily 10 (to enroll in one)."""
    mine = set(enrolled_subjects(ctx.student_code))
    return {"subjects": [s | {"enrolled": s["code"] in mine} for s in service.list_subjects()]}


class QuizArgs(BaseModel):
    subject: str | None = Field(None, description="Subject code; omit for any of the student's subjects")
    topic_id: int | None = None
    mode: Literal["due", "weak", "new", "any"] = Field(
        "any", description="due: spaced-repetition reviews due today; weak: topics they get wrong; "
                           "new: topics learned but not practised; any: best available")


def _pick_question(ctx: Context, a: QuizArgs) -> tuple[Question, Topic, Subject] | None:
    subjects = enrolled_subjects(ctx.student_code)
    codes = [a.subject.strip().upper()] if a.subject else list(subjects)
    for c in codes:
        if c not in subjects:
            raise PermissionError(f"{c} isn't one of your subjects.")
    subject_ids = [subjects[c]["id"] for c in codes]
    student, today = _student(ctx), config.local_today()
    with db.session() as s:
        base = (select(Question, Topic, Subject).join(Topic, Question.topic_id == Topic.id).join(Subject)
                .where(Question.status == "approved", Topic.subject_id.in_(subject_ids or [-1])))
        if a.topic_id:
            base = base.where(Topic.id == a.topic_id)
        answered_today = select(Review.question_id).where(Review.student_id == student.id, Review.last_answered_on == today)
        base = base.where(Question.id.not_in(answered_today))
        learned = select(TopicProgress.topic_id).where(TopicProgress.student_id == student.id)
        my_reviews = select(Review.question_id).where(Review.student_id == student.id)

        attempts = {
            "due": base.join(Review, (Review.question_id == Question.id) & (Review.student_id == student.id))
                       .where(Review.due_on <= today).order_by(Review.due_on, Review.box),
            "weak": base.join(Review, (Review.question_id == Question.id) & (Review.student_id == student.id))
                        .where(Review.correct < Review.attempts).order_by((Review.attempts - Review.correct).desc()),
            "new": base.where(Topic.id.in_(learned), Question.id.not_in(my_reviews)).order_by(Topic.position, Question.id),
        }
        order = {"due": ["due"], "weak": ["weak", "due"], "new": ["new"], "any": ["due", "weak", "new"]}[a.mode]
        for key in order:
            row = s.execute(attempts[key].limit(1)).first()
            if row:
                return row
        if a.mode == "any" or a.topic_id:
            return s.execute(base.order_by(Topic.position, Question.id).limit(1)).first()
    return None


@tool("quiz_me", S, QuizArgs, ui="quiz",
      label=lambda a: "Picking a question" + (f" on topic {a.topic_id}" if a.topic_id else f" ({a.mode})" if a.mode != "any" else ""))
def quiz_me(ctx: Context, a: QuizArgs) -> dict:
    """Pick one approved practice question for the student. The result does NOT include the answer:
    show the question and options, then wait for the student's choice and call check_answer.
    Never hint at or guess the answer before they choose."""
    row = _pick_question(ctx, a)
    if row is None:
        return {"question": None, "note": "No approved question fits. Suggest another mode, topic or subject."}
    q, topic, subject = row
    return {"question": {"question_id": q.id, "subject": subject.code, "topic_id": topic.id,
                         "topic": topic.title or topic.source, "prompt": q.prompt,
                         "options": [f"{LETTERS[i]}. {o}" for i, o in enumerate(q.options)]},
            "instructions": "The UI shows this question as buttons. Don't repeat the options; ask them to pick."}


class AnswerArgs(BaseModel):
    question_id: int
    choice: str = Field(description="The student's choice: A, B, C or D")

    @field_validator("choice")
    @classmethod
    def _letter(cls, v: str) -> str:
        m = re.search(r"\b([A-Da-d1-4])\b", v.strip()) or re.match(r"([A-Da-d1-4])", v.strip())
        if not m:
            raise ValueError("choice must be A, B, C or D")
        c = m.group(1).upper()
        return LETTERS[int(c) - 1] if c.isdigit() else c


@tool("check_answer", S, AnswerArgs, ui="answer", label=lambda a: f"Checking your answer ({a.choice})")
def check_answer(ctx: Context, a: AnswerArgs) -> dict:
    """Record the student's answer to a question (it updates their spaced-repetition schedule) and
    return whether it's right, the correct option, the explanation and the quote from the notes."""
    subjects = {v["id"] for v in enrolled_subjects(ctx.student_code).values()}
    with db.session() as s:
        q = s.get(Question, a.question_id)
        if q is None or q.status != "approved" or q.topic.subject_id not in subjects:
            raise PermissionError("That question isn't available to you.")
        options, topic_id, topic_title = q.options, q.topic_id, q.topic.title or q.topic.source
    result = service.submit_answer(ctx.student_code, a.question_id, LETTERS.index(a.choice))
    return {"question_id": a.question_id, "topic_id": topic_id, "topic": topic_title, "your_choice": a.choice,
            "correct": result["correct"], "correct_option": f"{LETTERS[result['answer_index']]}. {options[result['answer_index']]}",
            "options": [f"{LETTERS[i]}. {o}" for i, o in enumerate(options)],
            "explanation": result["explanation"], "evidence_from_notes": result["evidence"],
            "next_review": result["next_review"],
            **({"simple_explanation": result["simple"]} if result.get("simple") else {})}


class ReminderArgs(BaseModel):
    time: str = Field(pattern=r"^([01]\d|2[0-3]):[0-5]\d$", description="24-hour HH:MM, college time")


@tool("set_reminder_time", S, ReminderArgs, confirm=True,
      label=lambda a: f"Setting your reminder to {a.time}", summary=lambda a: f"Change your daily reminder to {a.time}")
def set_reminder_time(ctx: Context, a: ReminderArgs) -> dict:
    """Change the time of the student's daily reminder."""
    service.set_preferences(ctx.student_code, notify_time=a.time)
    return {"ok": True, "reminder_time": a.time}


class EnrollArgs(BaseModel):
    subject_code: str
    exam_date: date = Field(description="YYYY-MM-DD")


@tool("enroll_subject", S, EnrollArgs, confirm=True,
      label=lambda a: f"Adding {a.subject_code.upper()}",
      summary=lambda a: f"Add {a.subject_code.upper()} with the exam on {a.exam_date:%d %b %Y}")
def enroll_subject(ctx: Context, a: EnrollArgs) -> dict:
    """Add a subject (or change its exam date). The daily plan is rebuilt around the exam date."""
    if a.exam_date <= config.local_today():
        raise ValueError("The exam date must be in the future.")
    service.enroll(ctx.student_code, a.subject_code, a.exam_date)
    return {"ok": True, "subject": a.subject_code.upper(), "exam_date": a.exam_date.isoformat()}


class ReportArgs(BaseModel):
    question_id: int
    reason: str = Field(max_length=300, description="What looks wrong, in the student's words")


@tool("report_question", S, ReportArgs, confirm=True, label=lambda a: f"Reporting question {a.question_id}",
      summary=lambda a: f"Tell your faculty question {a.question_id} looks wrong: “{a.reason}”")
def report_question(ctx: Context, a: ReportArgs) -> dict:
    """Report a question that looks wrong. It goes back to faculty review."""
    service.report_question(a.question_id, reason=a.reason)
    return {"ok": True, "question_id": a.question_id}
