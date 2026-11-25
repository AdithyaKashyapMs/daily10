"""Saving conversations, messages and pending approvals. Every read checks who owns the conversation."""

import uuid
from datetime import datetime, timedelta, timezone

from sqlalchemy import delete, func, select

from daily10 import db
from daily10.db import AssistantConversation, AssistantMessage, PendingAction
from daily10.service import NotFound


def _now() -> datetime:
    return datetime.now(timezone.utc)


def create_conversation(owner_kind: str, owner_id: int, title: str) -> AssistantConversation:
    with db.session() as s:
        c = AssistantConversation(id=str(uuid.uuid4()), owner_kind=owner_kind, owner_id=owner_id,
                                  title=(" ".join(title.split())[:80] or "New chat"))
        s.add(c)
        s.commit()
        return c


def get_conversation(conversation_id: str, owner_kind: str, owner_id: int) -> AssistantConversation:
    with db.session() as s:
        c = s.get(AssistantConversation, conversation_id)
        if c is None or c.owner_kind != owner_kind or c.owner_id != owner_id:
            raise NotFound("No such conversation.")  # same answer for "not yours" and "doesn't exist"
        return c


def list_conversations(owner_kind: str, owner_id: int, limit: int = 30) -> list[dict]:
    with db.session() as s:
        rows = s.scalars(select(AssistantConversation).where(
            AssistantConversation.owner_kind == owner_kind, AssistantConversation.owner_id == owner_id)
            .order_by(AssistantConversation.updated_at.desc()).limit(limit)).all()
        return [{"id": c.id, "title": c.title, "updated_at": c.updated_at.isoformat()} for c in rows]


def delete_conversation(conversation_id: str, owner_kind: str, owner_id: int) -> None:
    get_conversation(conversation_id, owner_kind, owner_id)
    with db.session() as s:
        s.execute(delete(AssistantMessage).where(AssistantMessage.conversation_id == conversation_id))
        s.execute(delete(PendingAction).where(PendingAction.conversation_id == conversation_id))
        s.execute(delete(AssistantConversation).where(AssistantConversation.id == conversation_id))
        s.commit()


def add_message(conversation_id: str, role: str, content: str = "", tool_calls=None,
                tool_call_id: str | None = None, name: str | None = None, events=None) -> int:
    with db.session() as s:
        m = AssistantMessage(conversation_id=conversation_id, role=role, content=content or "", tool_calls=tool_calls,
                             tool_call_id=tool_call_id, name=name, events=events)
        s.add(m)
        c = s.get(AssistantConversation, conversation_id)
        c.updated_at = _now()
        s.commit()
        return m.id


def messages(conversation_id: str) -> list[AssistantMessage]:
    with db.session() as s:
        return list(s.scalars(select(AssistantMessage).where(AssistantMessage.conversation_id == conversation_id)
                              .order_by(AssistantMessage.id)))


def last_user_message_id(conversation_id: str) -> int | None:
    with db.session() as s:
        return s.scalar(select(func.max(AssistantMessage.id)).where(
            AssistantMessage.conversation_id == conversation_id, AssistantMessage.role == "user"))


def append_events(message_id: int, events: list[dict]) -> None:
    """Keep what the UI showed for a turn on that turn's user message, so it reopens the same."""
    if not events:
        return
    with db.session() as s:
        m = s.get(AssistantMessage, message_id)
        m.events = [*(m.events or []), *events]
        s.commit()


def user_messages_since(owner_kind: str, owner_id: int, minutes: int) -> int:
    with db.session() as s:
        return s.scalar(select(func.count()).select_from(AssistantMessage).join(AssistantConversation).where(
            AssistantConversation.owner_kind == owner_kind, AssistantConversation.owner_id == owner_id,
            AssistantMessage.role == "user", AssistantMessage.created_at > _now() - timedelta(minutes=minutes)))


# --- Pending approvals ---------------------------------------------------------------------

def create_pending(conversation_id: str, tool_call_id: str, tool: str, args: dict, summary: str) -> PendingAction:
    with db.session() as s:
        p = PendingAction(id=str(uuid.uuid4()), conversation_id=conversation_id, tool_call_id=tool_call_id,
                          tool=tool, args=args, summary=summary)
        s.add(p)
        s.commit()
        return p


def open_pending(conversation_id: str) -> list[PendingAction]:
    with db.session() as s:
        return list(s.scalars(select(PendingAction).where(PendingAction.conversation_id == conversation_id,
                                                          PendingAction.status == "pending")))


def get_pending(conversation_id: str, action_id: str) -> PendingAction:
    with db.session() as s:
        p = s.get(PendingAction, action_id)
        if p is None or p.conversation_id != conversation_id:
            raise NotFound("No such action.")
        return p


def resolve_pending(action_id: str, status: str) -> None:
    with db.session() as s:
        s.get(PendingAction, action_id).status = status
        s.commit()
