"""
Assistant API under /study/assistant. Works for students and faculty: the session (cookie or
Bearer token, see web_session.py) decides which assistant you get. A browser signed in as both
picks with "X-Daily10-Role: student|faculty". Replies stream as Server-Sent Events.

    POST   /assistant/chat                                  {conversation_id?, message}  -> SSE
    POST   /assistant/conversations/{id}/actions/{action}   {approve}                    -> SSE
    GET    /assistant/conversations                         your conversations
    GET    /assistant/conversations/{id}                    one conversation, as the UI showed it
    DELETE /assistant/conversations/{id}
    GET    /assistant/starters                              suggested workflows for your role
"""

import json
import logging
import os
from typing import Iterator

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field

from daily10 import auth, service, student_auth
from daily10.web_session import FACULTY_COOKIE, STUDENT_COOKIE, bearer, resolve
from daily10.assistant import Assistant, Context, store

log = logging.getLogger(__name__)
router = APIRouter(prefix="/study/assistant", tags=["Assistant"])

MAX_MESSAGES_PER_HOUR = int(os.getenv("ASSISTANT_MAX_MESSAGES_PER_HOUR", "60"))

STARTERS = {
    "student": [
        {"title": "Explain today's topic", "prompt": "Explain today's topic simply, with an example, then give me one quick question."},
        {"title": "Quiz my weak topics", "prompt": "Quiz me on my weakest topics, one question at a time."},
        {"title": "Am I on track?", "prompt": "Am I on track for my exams? If not, make me a catch-up plan for the next 7 days."},
        {"title": "Exam prep", "prompt": "What gets asked most in past papers for my subjects, and which of those topics should I revise first?"},
    ],
    "faculty": [
        {"title": "Review flagged questions", "prompt": "Go through the flagged questions in CC701 with the reviewer agent and tell me what to approve, fix or reject."},
        {"title": "Weekly class report", "prompt": "Write this week's class report for CC701, with three actions."},
        {"title": "Remedial questions", "prompt": "Find the CC701 topic students struggle with most and draft 3 new questions on it, checked by the reviewer."},
        {"title": "Exam coverage check", "prompt": "Which CC701 topics are asked most in past papers but have few approved questions?"},
    ],
}


def _student_ctx(student) -> Context:
    return Context(role="student", actor=student.name or "there", owner_id=student.id, student_code=student.code)


def _faculty_ctx(faculty) -> Context:
    return Context(role="faculty", actor=faculty.name, owner_id=faculty.id)


def context(request: Request) -> Context:
    """Who is calling: a Bearer token (student or faculty), else the session cookie for the role asked."""
    token = bearer(request)
    if token:
        student = student_auth.student_for_token(token)
        if student:
            return _student_ctx(student)
        faculty = auth.faculty_for_token(token)
        if faculty:
            return _faculty_ctx(faculty)
        raise HTTPException(status_code=401, detail="Please sign in again.")
    role = request.headers.get("x-daily10-role", "student")
    if role == "faculty":
        faculty = resolve(request, FACULTY_COOKIE, auth.faculty_for_token, "Please log in again.")
        if faculty:
            return _faculty_ctx(faculty)
    else:
        student = resolve(request, STUDENT_COOKIE, student_auth.student_for_token, "Please sign in again.")
        if student:
            return _student_ctx(student)
    raise HTTPException(status_code=401, detail="Please sign in.")


def _sse(events: Iterator[dict], conversation: dict | None = None) -> StreamingResponse:
    def body():
        if conversation:
            yield f"data: {json.dumps({'type': 'conversation', **conversation})}\n\n"
        try:
            for event in events:
                yield f"data: {json.dumps(event, default=str, ensure_ascii=False)}\n\n"
        except (service.NotFound, ValueError) as e:
            yield f"data: {json.dumps({'type': 'error', 'message': str(e)})}\n\n"
        except Exception as e:
            log.exception("Assistant turn failed")
            yield f"data: {json.dumps({'type': 'error', 'message': f'Something went wrong ({type(e).__name__}).'})}\n\n"
        yield 'data: {"type": "done"}\n\n'

    return StreamingResponse(body(), media_type="text/event-stream",
                             headers={"Cache-Control": "no-cache, no-transform", "X-Accel-Buffering": "no"})


class ChatIn(BaseModel):
    message: str = Field(..., min_length=1, max_length=4000)
    conversation_id: str | None = None


@router.post("/chat")
def chat(body: ChatIn, ctx: Context = Depends(context)):
    if store.user_messages_since(ctx.role, ctx.owner_id, 60) >= MAX_MESSAGES_PER_HOUR:
        raise HTTPException(status_code=429, detail="You've sent a lot of messages this hour. Take a short break!")
    if body.conversation_id:
        try:
            convo = store.get_conversation(body.conversation_id, ctx.role, ctx.owner_id)
        except service.NotFound as e:
            raise HTTPException(status_code=404, detail=str(e))
    else:
        convo = store.create_conversation(ctx.role, ctx.owner_id, body.message)
    assistant = Assistant(ctx, convo.id)
    return _sse(assistant.chat(body.message), {"id": convo.id, "title": convo.title})


class DecisionIn(BaseModel):
    approve: bool


@router.post("/conversations/{conversation_id}/actions/{action_id}")
def decide(conversation_id: str, action_id: str, body: DecisionIn, ctx: Context = Depends(context)):
    try:
        store.get_conversation(conversation_id, ctx.role, ctx.owner_id)
        pending = store.get_pending(conversation_id, action_id)
    except service.NotFound as e:
        raise HTTPException(status_code=404, detail=str(e))
    if pending.status != "pending":
        raise HTTPException(status_code=409, detail="That change was already decided.")
    return _sse(Assistant(ctx, conversation_id).resolve(action_id, body.approve))


@router.get("/conversations")
def conversations(ctx: Context = Depends(context)):
    return store.list_conversations(ctx.role, ctx.owner_id)


@router.get("/conversations/{conversation_id}")
def conversation(conversation_id: str, ctx: Context = Depends(context)):
    """The conversation as the UI showed it: each user message with the events of its turn."""
    try:
        convo = store.get_conversation(conversation_id, ctx.role, ctx.owner_id)
    except service.NotFound as e:
        raise HTTPException(status_code=404, detail=str(e))
    pending = {p.id for p in store.open_pending(conversation_id)}
    turns = []
    for m in store.messages(conversation_id):
        if m.role == "user":
            turns.append({"message": m.content, "events": m.events or []})
    return {"id": convo.id, "title": convo.title, "role": ctx.role, "turns": turns, "pending": sorted(pending)}


@router.delete("/conversations/{conversation_id}")
def delete(conversation_id: str, ctx: Context = Depends(context)):
    try:
        store.delete_conversation(conversation_id, ctx.role, ctx.owner_id)
    except service.NotFound as e:
        raise HTTPException(status_code=404, detail=str(e))
    return {"ok": True}


@router.get("/starters")
def starters(ctx: Context = Depends(context)):
    if ctx.role == "faculty":
        subjects = sorted(service.list_subjects(), key=lambda s: -s["topics"])  # the one with content
        code = subjects[0]["code"] if subjects else "CC701"
        return [{k: v.replace("CC701", code) for k, v in s.items()} for s in STARTERS["faculty"]]
    return STARTERS["student"]
