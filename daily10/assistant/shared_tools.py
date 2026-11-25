"""Tools both roles get: the visible plan, and retrieval over the notes and past papers."""

from typing import Literal

from pydantic import BaseModel, Field

from daily10 import retrieval
from daily10.assistant.registry import Context, tool

BOTH = {"student", "faculty"}


class PlanStep(BaseModel):
    title: str = Field(max_length=120)
    status: Literal["pending", "in_progress", "done"] = "pending"


class PlanArgs(BaseModel):
    steps: list[PlanStep] = Field(min_length=1, max_length=8)


@tool("update_plan", BOTH, PlanArgs, label=lambda a: "Updating the plan", ui="plan")
def update_plan(ctx: Context, a: PlanArgs) -> dict:
    """For any request that needs 3 or more steps: call this FIRST with the steps you will take,
    then again as each step starts (in_progress) and finishes (done). The user sees this checklist."""
    ctx.scratch["plan"] = [s.model_dump() for s in a.steps]
    return {"ok": True, "plan": ctx.scratch["plan"]}


class SearchArgs(BaseModel):
    subject: str = Field(description="Subject code, e.g. CC701")
    query: str = Field(description="Specific keywords. Rephrase and search again if results are weak.")
    topic_id: int | None = Field(None, description="Only search this topic")


class TopicArgs(BaseModel):
    topic_id: int


class PastPaperArgs(BaseModel):
    subject: str
    query: str | None = Field(None, description="Keywords; omit to list the most recent questions")


def _check_subject(ctx: Context, subject: str) -> str:
    code = subject.strip().upper()
    allowed = ctx.scratch.get("subjects")  # students: only their enrolled subjects
    if allowed is not None and code not in allowed:
        raise PermissionError(f"{code} isn't one of your subjects ({', '.join(sorted(allowed)) or 'none yet'}).")
    return code


def search_notes(ctx: Context, a: SearchArgs) -> dict:
    """Keyword search over a subject's lecture notes. Returns passages with citation ids like T12#3.
    Cite the ids you use in your answer, in square brackets."""
    hits = retrieval.search_notes(_check_subject(ctx, a.subject), a.query, top_k=4, topic_id=a.topic_id)
    return {"passages": [{**h, "content": h["content"][:900]} for h in hits]}


def read_topic(ctx: Context, a: TopicArgs) -> dict:
    """A whole topic: its notes as citable passages, summary, key points and past exam questions on it."""
    topic = retrieval.read_topic(a.topic_id)
    _check_subject(ctx, topic["subject"])
    used, passages = 0, []
    for p in topic["passages"]:
        if used > 6000:
            break
        passages.append(p)
        used += len(p["content"])
    return {**topic, "passages": passages, "topic": topic["title"]}


def search_past_papers(ctx: Context, a: PastPaperArgs) -> dict:
    """Past exam questions (ids like P7) with year, marks and the topic each matches."""
    return {"questions": retrieval.search_past_papers(_check_subject(ctx, a.subject), a.query, top_k=8)}


tool("search_notes", BOTH, SearchArgs, label=lambda a: f"Searching {a.subject.upper()} notes for “{a.query}”")(search_notes)
tool("read_topic", BOTH, TopicArgs, label=lambda a: f"Reading topic {a.topic_id}")(read_topic)
tool("search_past_papers", BOTH, PastPaperArgs,
     label=lambda a: f"Checking {a.subject.upper()} past papers" + (f" for “{a.query}”" if a.query else ""))(search_past_papers)
