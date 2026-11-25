"""
MCP server for the university side of Daily 10: faculty and admins can manage subjects,
work through the question review queue, see how a class is doing, and ask questions over
the course notes from Claude Desktop, Claude Code, Cursor or any MCP client.

Tools
  Data (read-only)      list_subjects, subject_overview, list_questions, get_question, class_insights
  Retrieval (read-only) search_notes, read_topic, search_past_papers
      The client's own model can do agentic RAG with these: search, read around a hit,
      search again, and cite passage ids ("T12#3", "P7").
  Agents (call an LLM)  ask_notes, review_question, draft_questions
      This server's sub-agents (daily10/assistant/subagents.py): researcher, reviewer (a different
      model family) and writer. Same tools and citation checks as the in-app assistant; citations
      must be passages the agent actually retrieved. Agents recommend; they never approve.
  Actions (write)       set_question_status, edit_question, create_subject, add_notes,
                        add_past_paper, generate_questions, run_ai_check

Prompts: review_queue (walk the flagged questions with faculty), class_report (weekly summary).

Who can use it
  stdio: runs as the local user with direct database access, like the CLI.
  HTTP:  every request needs "Authorization: Bearer <token>", either a faculty login token
         (POST /study/faculty/login) or the university key STUDY_ADMIN_KEY.

Run:
    python -m daily10.mcp_server                                     # stdio
    python -m daily10.mcp_server --transport streamable-http --port 8765   # http://127.0.0.1:8765/mcp
"""

import argparse
import contextvars
import hmac
import json
import logging
import os
from pathlib import Path
from typing import Any

import anyio
from mcp.server.mcpserver import MCPServer
from mcp.server.mcpserver.exceptions import ToolError
from mcp.types import ToolAnnotations
from pydantic import ValidationError

from daily10 import auth, content, insights, retrieval, service
from daily10.assistant import subagents
from daily10.assistant.registry import Context

# On stdio, stdout carries the protocol: logs go to stderr only.
logging.basicConfig(level=logging.WARNING, format="%(levelname)s %(name)s: %(message)s")

ACTOR: contextvars.ContextVar[str] = contextvars.ContextVar(
    "actor", default=os.getenv("DAILY10_MCP_ACTOR", "local MCP client"))
_transport = "stdio"

mcp = MCPServer(
    name="daily10-faculty",
    title="Daily 10 (faculty)",
    version="1.0.0",
    log_level="WARNING",
    instructions=(
        "Daily 10 turns a course's lecture notes and past exam papers into a 10-minute daily study "
        "session for students. Faculty approve every question before students see it. "
        "Start with list_subjects / subject_overview. To answer questions about course content, either "
        "search yourself (search_notes, read_topic, search_past_papers; cite passage ids like T12#3) or "
        "call ask_notes. For the review queue, use list_questions(flagged_only=true), review_question for "
        "a recommendation, and only call set_question_status or edit_question after the faculty member "
        "has agreed. class_insights shows coverage, students behind, and the weakest topics."
    ),
)

READ_ONLY = ToolAnnotations(read_only_hint=True, idempotent_hint=True, open_world_hint=False)
LLM_READ = ToolAnnotations(read_only_hint=True, open_world_hint=True)
WRITE = ToolAnnotations(read_only_hint=False, destructive_hint=False, idempotent_hint=True, open_world_hint=False)
APPEND = ToolAnnotations(read_only_hint=False, destructive_hint=False, idempotent_hint=False, open_world_hint=False)
LLM_WRITE = ToolAnnotations(read_only_hint=False, destructive_hint=False, idempotent_hint=False, open_world_hint=True)


def _llm(kind: str = "main"):
    """JSON-mode Groq model. "judge" uses a different model family from the one that wrote the questions."""
    from daily10 import config
    from daily10.llm import get_json_llm

    if kind == "judge":
        return get_json_llm(models=[config.JUDGE_MODEL, *config.FALLBACK_MODELS])
    return get_json_llm()


def _agent_model(kind: str = "main"):
    """Tool-calling models for the sub-agents ("judge": the reviewer's different model family)."""
    from daily10.llm import get_agent_model

    return get_agent_model(kind)


def _ctx() -> Context:
    """The MCP client acts as a faculty member; sub-agents run with this context."""
    return Context(role="faculty", actor=ACTOR.get(), owner_id=0, model_factory=lambda kind: _agent_model(kind))


async def _run(fn, *args, **kwargs):
    """Run blocking database / LLM code off the event loop, mapping errors to tool errors."""
    ctx = contextvars.copy_context()
    try:
        return await anyio.to_thread.run_sync(lambda: ctx.run(fn, *args, **kwargs))
    except (service.NotFound, ValueError, subagents.AgentError) as e:
        raise ToolError(str(e)) from e
    except RuntimeError as e:  # e.g. no GROQ_API_KEY
        raise ToolError(str(e)) from e


# --- Data ------------------------------------------------------------------------------------

@mcp.tool(annotations=READ_ONLY)
async def list_subjects() -> dict[str, Any]:
    """Every subject with its code, name, department, semester and number of topics."""
    return {"subjects": await _run(service.list_subjects)}


@mcp.tool(annotations=READ_ONLY)
async def subject_overview(subject: str) -> dict[str, Any]:
    """One subject at a glance: topics in syllabus order with exam weight (times asked in past papers)
    and question counts, the review queue (drafts, flagged or reported, not yet AI-checked),
    past-paper questions and enrolled students.

    Args:
        subject: Subject code, e.g. "CC701".
    """
    return await _run(insights.subject_overview, subject)


@mcp.tool(annotations=READ_ONLY)
async def list_questions(subject: str, status: str | None = None, flagged_only: bool = False,
                         topic_id: int | None = None, limit: int = 25) -> dict[str, Any]:
    """Questions for a subject with answers, evidence quotes and review status. Flagged (by the
    independent AI check) and student-reported questions come first.

    Args:
        subject: Subject code.
        status: draft | approved | rejected | auto_rejected. Omit for all.
        flagged_only: Only questions the AI check flagged or students reported.
        topic_id: Only questions on this topic.
        limit: Maximum questions to return (1-100).
    """
    rows = await _run(service.list_questions, subject, status)
    rows = insights.filter_questions(rows, flagged_only, topic_id)
    limit = max(1, min(limit, 100))
    return {"total": len(rows), "returned": min(len(rows), limit), "questions": rows[:limit]}


@mcp.tool(annotations=READ_ONLY)
async def get_question(question_id: int) -> dict[str, Any]:
    """One question in full: options, marked answer, evidence quote, review status and reason,
    student reports, automatic check results, and how students have answered it."""
    return await _run(insights.question_detail, question_id)


@mcp.tool(annotations=READ_ONLY)
async def class_insights(subject: str) -> dict[str, Any]:
    """How the class is doing in a subject: average coverage and accuracy, students behind schedule
    or inactive for a week, weakest topics, hardest questions, reported questions, and per-student
    and per-topic numbers. Students appear by name only (no emails).

    Args:
        subject: Subject code.
    """
    return await _run(insights.class_insights, subject)


# --- Retrieval (for the client's own agentic RAG) ---------------------------------------------

@mcp.tool(annotations=READ_ONLY)
async def search_notes(subject: str, query: str, top_k: int = 5, topic_id: int | None = None) -> dict[str, Any]:
    """Keyword (BM25) search over a subject's lecture notes. Returns passages with citation ids
    like "T12#3" (topic 12, passage 3). Use specific technical terms; if results are weak, search
    again with different words. Expand a hit with read_topic.

    Args:
        subject: Subject code.
        query: Keywords or a question.
        top_k: Passages to return (1-10).
        topic_id: Only search this topic.
    """
    hits = await _run(retrieval.search_notes, subject, query, max(1, min(top_k, 10)), topic_id)
    return {"query": query, "passages": hits}


@mcp.tool(annotations=READ_ONLY)
async def read_topic(topic_id: int) -> dict[str, Any]:
    """A whole topic: its notes as citable passages, generated summary and key points, exam weight,
    past exam questions matched to it, question counts, and the previous/next topic ids."""
    return await _run(retrieval.read_topic, topic_id)


@mcp.tool(annotations=READ_ONLY)
async def search_past_papers(subject: str, query: str | None = None, top_k: int = 10) -> dict[str, Any]:
    """Past exam questions (ids like "P7") with year, marks and the topic each was matched to.
    Without a query, returns the most recent ones.

    Args:
        subject: Subject code.
        query: Keywords, e.g. "deadlock conditions".
        top_k: Questions to return (1-50).
    """
    return {"questions": await _run(retrieval.search_past_papers, subject, query, max(1, min(top_k, 50)))}


# --- Agents (server-side agentic RAG) ---------------------------------------------------------

@mcp.tool(annotations=LLM_READ)
async def ask_notes(subject: str, question: str) -> subagents.NotesAnswer:
    """Ask this server's RAG agent a question about a subject's notes and past papers. It searches,
    reads around good hits, rephrases weak searches, and answers with verified citations.
    Prefer search_notes / read_topic if you'd rather reason over the passages yourself.

    Args:
        subject: Subject code.
        question: E.g. "How do the notes explain the Banker's algorithm, and how often is it asked?"
    """
    ctx = _ctx()
    return await _run(lambda: subagents.ask_notes(subject, question, ctx))


@mcp.tool(annotations=LLM_READ)
async def review_question(question_id: int) -> subagents.QuestionReview:
    """An agent (a different model family from the question writer) checks one question against the
    notes, searching other topics too, and recommends approve / reject / edit with cited reasons and,
    if fixable, a suggested edit whose evidence is verified. Changes nothing: apply the outcome with
    set_question_status or edit_question once the faculty member agrees."""
    ctx = _ctx()
    return await _run(lambda: subagents.review_question(question_id, ctx))


@mcp.tool(annotations=LLM_WRITE)
async def draft_questions(subject: str, focus: str, n: int = 3) -> subagents.DraftResult:
    """Write new questions on a chosen area (e.g. a weak topic from class_insights, or something often
    asked in past papers). An agent finds the right notes first; each question is saved under the topic
    of the passage it cites, after the usual checks (evidence quoted from the notes, 4 distinct options,
    no near-duplicates). Saved as drafts: students see them only after approval.

    Args:
        subject: Subject code.
        focus: What to test, e.g. "difference between HPA and VPA".
        n: Number of questions (1-6).
    """
    ctx = _ctx()
    return await _run(lambda: subagents.draft_questions(subject, focus, n, ctx))


# --- Actions ---------------------------------------------------------------------------------

@mcp.tool(annotations=WRITE)
async def set_question_status(question_id: int, status: str, reason: str = "") -> dict[str, Any]:
    """Approve or reject a question (or send it back to draft). Only approved questions reach students.
    Confirm with the faculty member before approving.

    Args:
        question_id: The question.
        status: approved | rejected | draft.
        reason: Why (recommended for rejections).
    """
    actor = ACTOR.get()
    note = reason.strip() or ("" if status == "approved" else f"{status} by {actor}")
    await _run(service.set_question_status, question_id, status, note)
    return {"ok": True, "question_id": question_id, "status": status, "by": actor}


@mcp.tool(annotations=WRITE)
async def edit_question(question_id: int, prompt: str | None = None, options: list[str] | None = None,
                        answer_index: int | None = None, explanation: str | None = None,
                        evidence: str | None = None) -> dict[str, Any]:
    """Change a question's wording, options, marked answer, explanation or evidence (e.g. a
    review_question suggestion). The evidence must be a word-for-word quote from the topic's notes.
    The question goes back to draft for approval.

    Args:
        question_id: The question.
        prompt: New question text.
        options: Exactly 4 distinct options.
        answer_index: Index (0-3) of the correct option.
        explanation: Why the answer is correct.
        evidence: Quote from the notes that supports the answer.
    """
    changes = {"prompt": prompt, "options": options, "answer_index": answer_index,
               "explanation": explanation, "evidence": evidence}
    try:
        return await _run(service.edit_question, question_id, changes, ACTOR.get())
    except ValidationError as e:
        raise ToolError(e.errors()[0]["msg"]) from e


def _create_subject(code: str, name: str, department: str, semester: int) -> dict[str, Any]:
    try:
        service.get_subject(code)
    except service.NotFound:
        s = service.create_subject(code, name, department, semester)
        return {"code": s.code, "name": s.name, "department": s.department, "semester": s.semester}
    raise ValueError(f"Subject {code.strip().upper()} already exists.")


@mcp.tool(annotations=APPEND)
async def create_subject(code: str, name: str, department: str = "", semester: int = 0) -> dict[str, Any]:
    """Create a subject, e.g. code "21CS53", name "Database Management Systems"."""
    return await _run(_create_subject, code, name, department, semester)


def _allowed_roots() -> list[Path]:
    env = os.getenv("DAILY10_MCP_FILE_ROOTS")
    if env:
        return [Path(p).expanduser().resolve() for p in env.split(os.pathsep) if p.strip()]
    return [Path.home().resolve()] if _transport == "stdio" else []


def _check_path(path: str) -> str:
    p = Path(path).expanduser().resolve()
    roots = _allowed_roots()
    if not roots:
        raise ValueError("Reading files is off on HTTP. Set DAILY10_MCP_FILE_ROOTS to the upload folder(s).")
    if not any(p == r or r in p.parents for r in roots):
        raise ValueError(f"{path} is outside the allowed folders: {', '.join(map(str, roots))}")
    if not p.is_file():
        raise ValueError(f"No file at {path}")
    return str(p)


def _add_notes(subject: str, paths: list[str]) -> dict[str, Any]:
    files = [_check_path(p) for p in paths]
    texts = [(Path(f).name, content.read_file(f)) for f in files]
    added = service.add_notes(subject, texts)
    return {"topics_added": added, "files": [Path(f).name for f in files],
            "next": "generate_questions to write summaries and questions for the new topics"}


@mcp.tool(annotations=APPEND)
async def add_notes(subject: str, paths: list[str]) -> dict[str, Any]:
    """Add lecture notes (PDF, DOCX, PPTX, HTML or TXT files on this machine), in syllabus order.
    They're split into daily topics appended after the existing ones.

    Args:
        subject: Subject code.
        paths: File paths, in syllabus order.
    """
    return await _run(_add_notes, subject, paths)


def _add_paper(subject: str, path: str, year: int | None) -> dict[str, Any]:
    f = _check_path(path)
    year = year or content.year_from_name(Path(f).name)
    n = service.add_past_paper(subject, content.read_file(f), year)
    return {"questions_added": n, "year": year}


@mcp.tool(annotations=APPEND)
async def add_past_paper(subject: str, path: str, year: int | None = None) -> dict[str, Any]:
    """Add a past exam paper. Each question is matched to a topic, raising that topic's exam weight.
    Add notes first.

    Args:
        subject: Subject code.
        path: The paper's file path.
        year: Exam year (read from the file name if omitted).
    """
    return await _run(_add_paper, subject, path, year)


@mcp.tool(annotations=LLM_WRITE)
async def generate_questions(subject: str, limit: int = 5) -> dict[str, Any]:
    """Write the title, summary, key points and draft questions for topics that don't have them yet,
    a few topics per call (free LLM tiers have daily limits). Questions whose evidence isn't in the
    notes are auto-rejected. Follow with run_ai_check, then review.

    Args:
        subject: Subject code.
        limit: Topics to process in this call (1-20).
    """
    return await _run(lambda: service.generate_questions(subject, _llm(), True, max(1, min(limit, 20))))


@mcp.tool(annotations=LLM_WRITE)
async def run_ai_check(subject: str, recheck: bool = False) -> dict[str, Any]:
    """Independent AI check of draft questions: a different model answers each blind from the notes.
    Disagreements are marked "AI check flagged: ..." and move to the front of the review queue.
    It never approves anything.

    Args:
        subject: Subject code.
        recheck: Also re-check drafts that were already checked.
    """
    return await _run(lambda: service.check_questions(subject, _llm("judge"), recheck))


# --- Prompts ---------------------------------------------------------------------------------

@mcp.prompt(title="Review the flagged questions")
def review_queue(subject: str) -> str:
    """Go through a subject's flagged and reported questions with the faculty member."""
    return (
        f"Help me review the question queue for subject {subject}.\n"
        f"1. Call subject_overview to see the queue size. If many drafts are not AI-checked, offer run_ai_check.\n"
        f"2. Call list_questions(subject='{subject}', status='draft', flagged_only=true).\n"
        f"3. For each question, call review_question and show me: the question, the marked answer, the issue, "
        f"your recommendation with the cited passages, and any suggested edit.\n"
        f"4. Wait for my decision on each. Only then call set_question_status or edit_question. Never approve "
        f"anything I haven't agreed to.\n"
        f"5. When the flagged ones are done, offer to continue with unflagged drafts in batches of 5."
    )


@mcp.prompt(title="Weekly class report")
def class_report(subject: str) -> str:
    """A short weekly report on how the class is doing, with suggested follow-ups."""
    return (
        f"Write a short weekly report for subject {subject}.\n"
        f"Use class_insights for coverage, students behind or inactive, weakest topics and hardest questions. "
        f"For the 2-3 weakest topics, use search_past_papers to check how often they're examined, and "
        f"search_notes / read_topic to say what the notes cover there (cite passage ids). "
        f"Check whether any hardest question is flawed rather than hard (get_question; review_question if "
        f"in doubt). End with 3 concrete actions, e.g. draft_questions on a weak topic or a reminder to "
        f"inactive students. Use student names only as needed; don't paste the whole table."
    )


# --- HTTP auth and entry point -----------------------------------------------------------------

def actor_for_token(token: str) -> str | None:
    """Who a bearer token belongs to: the university key, a faculty login, or nobody."""
    if not token:
        return None
    key = auth.invite_code()
    if key and hmac.compare_digest(token.encode(), key.encode()):
        return "university admin key"
    f = auth.faculty_for_token(token)
    return f.name if f else None


class BearerAuth:
    """ASGI middleware: every HTTP request needs a valid bearer token; the caller is recorded."""

    def __init__(self, app):
        self.app = app

    async def __call__(self, scope, receive, send):
        if scope["type"] != "http":
            return await self.app(scope, receive, send)
        header = dict(scope.get("headers") or []).get(b"authorization", b"").decode()
        token = header[7:].strip() if header.lower().startswith("bearer ") else ""
        actor = await anyio.to_thread.run_sync(actor_for_token, token) if token else None
        if actor is None:
            body = json.dumps({"error": "Send Authorization: Bearer <faculty login token or STUDY_ADMIN_KEY>"}).encode()
            await send({"type": "http.response.start", "status": 401,
                        "headers": [(b"content-type", b"application/json"), (b"www-authenticate", b"Bearer")]})
            await send({"type": "http.response.body", "body": body})
            return
        reset = ACTOR.set(actor)
        try:
            await self.app(scope, receive, send)
        finally:
            ACTOR.reset(reset)


def http_app(host: str = "127.0.0.1"):
    # Stateless: each request runs in its own context, so the caller identity can't leak between requests.
    return BearerAuth(mcp.streamable_http_app(stateless_http=True, json_response=True, host=host))


def main() -> None:
    global _transport
    parser = argparse.ArgumentParser(description="Daily 10 faculty MCP server")
    parser.add_argument("--transport", choices=["stdio", "streamable-http"], default="stdio")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8765)
    args = parser.parse_args()
    _transport = args.transport

    if args.transport == "stdio":
        mcp.run("stdio")
        return
    if not auth.invite_code() and not auth.any_faculty():
        raise SystemExit("HTTP needs a way to log in: set STUDY_ADMIN_KEY or create a faculty account first.")
    import uvicorn

    uvicorn.run(http_app(args.host), host=args.host, port=args.port, log_level="warning")


if __name__ == "__main__":
    main()
