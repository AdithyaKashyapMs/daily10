"""
The assistant's agent loop: think -> act -> observe, until it can answer.

    user message
      -> model (streamed; native tool calling, Groq model fallback chain)
      -> tool calls: validated, role-checked, run -> results back to the model -> repeat
      -> a tool that changes data pauses the loop: the user sees an Approve / Cancel card;
         resolve() runs it (or records the refusal) and the loop carries on from there
      -> final answer: [T12#3]-style citations checked against passages the tools really returned

Everything the UI needs arrives as events (streamed over SSE by the API):
    token      a piece of the reply text
    step       a tool starting / finishing ("Searching CC701 notes for 'cron'"), with a short result
    plan       the agent's checklist (update_plan)
    quiz       a practice question card (no answer)          answer   feedback after check_answer
    confirm    a proposed change waiting for approval         confirm_resolved   approved / declined
    message    the final reply, with verified citations and any unverified ones
    waiting    paused for approval                            error    something went wrong
Non-token events are also saved on the turn's user message, so a conversation reopens as it looked.

Sub-agents (subagents.py) run on the same tools, tool calling, validation and citation checks,
headless; the faculty Copilot hands them work as tools (review_question, draft_questions).

Safety: tools act only as the signed-in user; arguments are validated (errors go back to the model
to fix); MAX_STEPS bounds each turn; tool output is passed as data, and the prompt says so.
"""

import json
import logging
import time
import uuid
from typing import Iterator

from langchain_core.messages import AIMessage, HumanMessage, SystemMessage, ToolMessage

from daily10 import service
from daily10.assistant import citations, faculty_tools, prompts, shared_tools, store, student_tools  # noqa: F401 (registers tools)
from daily10.assistant.registry import Context, Tool, execute, parse_args, summarize, tools_for

log = logging.getLogger(__name__)

MAX_STEPS = 8                 # model calls per turn
HISTORY_MESSAGES = 40         # messages of memory sent to the model
STORED_RESULT_CHARS = 20000   # a tool result as saved
TOOL_RESULT_CHARS = 6000      # a tool result as the model sees it in the current turn
OLD_TOOL_RESULT_CHARS = 600   # ... and in earlier turns (keeps long chats within budget)


class AssistantUnavailable(RuntimeError):
    pass


class Assistant:
    def __init__(self, ctx: Context, conversation_id: str, llm=None):
        self.ctx, self.cid = ctx, conversation_id
        self.tools = tools_for(ctx.role)
        self._llm = llm
        self.turn_events: list[dict] = []
        self.user_message_id: int | None = None
        if ctx.role == "student":
            subjects = student_tools.enrolled_subjects(ctx.student_code)
            ctx.scratch["subjects"] = set(subjects)
            self.subject_lines = [f"{c} {v['name']} (exam {v['exam_date']:%d %b %Y})" for c, v in subjects.items()]
        else:
            self.subject_lines = [f"{s['code']} {s['name']}" for s in service.list_subjects()]

    @property
    def llm(self):
        if self._llm is None:
            from daily10.llm import get_tool_llm

            self._llm = get_tool_llm([t.schema() for t in self.tools.values()])
        return self._llm

    # --- entry points ------------------------------------------------------------------------

    def chat(self, text: str) -> Iterator[dict]:
        """A new user message. Any change still waiting for approval counts as declined."""
        for p in store.open_pending(self.cid):
            store.resolve_pending(p.id, "expired")
            self._save_tool_result(p.tool_call_id, p.tool, {
                "declined": True, "note": "The user didn't approve this; they sent a new message instead."})
            self.turn_events.append({"type": "confirm_resolved", "action_id": p.id, "status": "expired"})
        self.user_message_id = store.add_message(self.cid, "user", text)
        yield from self._run()

    def resolve(self, action_id: str, approve: bool) -> Iterator[dict]:
        """The user approved or declined a proposed change: do it (or not) and continue."""
        p = store.get_pending(self.cid, action_id)
        if p.status != "pending":
            raise ValueError("That change was already decided.")
        self.user_message_id = store.last_user_message_id(self.cid)
        store.resolve_pending(p.id, "approved" if approve else "rejected")
        yield self._emit({"type": "confirm_resolved", "action_id": p.id, "status": "approved" if approve else "rejected"})
        if approve:
            tool = self.tools[p.tool]
            yield from self._execute(p.tool_call_id, tool, tool.args.model_validate(p.args))
        else:
            self._save_tool_result(p.tool_call_id, p.tool, {"declined": True, "note": "The user chose not to do this."})
        yield from self._run()

    # --- the loop ----------------------------------------------------------------------------

    def _run(self) -> Iterator[dict]:
        try:
            for _ in range(MAX_STEPS):
                ai = yield from self._think()
                calls = self._calls(ai)
                store.add_message(self.cid, "assistant", _text(ai.content), tool_calls=calls or None)
                if not calls:
                    yield self._final(_text(ai.content))
                    return
                waiting = False
                for call in calls:
                    if waiting:
                        self._save_tool_result(call["id"], call["name"], {
                            "error": "Not run: an earlier change is waiting for the user's approval. "
                                     "Call this again afterwards if it's still needed."})
                        continue
                    waiting = yield from self._handle(call)
                if waiting:
                    yield self._emit({"type": "waiting"})
                    return
            yield from self._wrap_up()
        except AssistantUnavailable as e:
            yield self._emit({"type": "error", "message": str(e)})
        finally:
            if self.user_message_id:
                store.append_events(self.user_message_id, self.turn_events)
                self.turn_events = []

    def _think(self):
        """One model call, streamed. Returns the complete AIMessage."""
        messages = self._model_messages()
        acc = None
        try:
            for chunk in self.llm.stream(messages):
                piece = _text(chunk.content)
                if piece:
                    yield {"type": "token", "text": piece}
                acc = chunk if acc is None else acc + chunk
        except Exception as e:
            log.warning(f"Assistant model call failed: {e}")
            raise AssistantUnavailable("The AI service is busy or unreachable right now. Try again in a minute.") from e
        if acc is None:
            raise AssistantUnavailable("The AI service returned nothing. Try again.")
        bad = [{"id": c.get("id") or f"call_{uuid.uuid4().hex[:12]}", "name": c.get("name") or "unknown",
                "args": {}, "invalid": c.get("error") or "arguments were not valid JSON"}
               for c in (getattr(acc, "invalid_tool_calls", None) or [])]
        return AIMessage(content=acc.content, tool_calls=list(acc.tool_calls or []),
                         additional_kwargs={"invalid_calls": bad})

    def _calls(self, ai: AIMessage) -> list[dict]:
        calls = [{"id": c.get("id") or f"call_{uuid.uuid4().hex[:12]}", "name": c["name"], "args": c.get("args") or {}}
                 for c in ai.tool_calls]
        return calls + ai.additional_kwargs.get("invalid_calls", [])

    def _handle(self, call: dict):
        """Validate and run (or propose) one tool call. Returns True if it now waits for approval."""
        tool = self.tools.get(call["name"])
        if call.get("invalid"):
            self._save_tool_result(call["id"], call["name"], {"error": f"Invalid call: {call['invalid']}. Try again."})
            return False
        if tool is None:
            self._save_tool_result(call["id"], call["name"], {
                "error": f"There is no tool called {call['name']} for you. Available: {', '.join(sorted(self.tools))}"})
            return False
        args, error = parse_args(tool, call["args"])
        if args is None:
            yield self._emit({"type": "step", "id": call["id"], "tool": tool.name, "label": tool.name.replace("_", " "),
                              "status": "error", "summary": "fixing its arguments"})
            self._save_tool_result(call["id"], tool.name, {"error": error})
            return False
        if tool.confirm:
            summary = tool.summary(args) if tool.summary else tool.describe_call(args)
            p = store.create_pending(self.cid, call["id"], tool.name, args.model_dump(mode="json"), summary)
            yield self._emit({"type": "confirm", "action_id": p.id, "tool": tool.name, "summary": summary,
                              "args": args.model_dump(mode="json")})
            return True
        yield from self._execute(call["id"], tool, args)
        return False

    def _execute(self, call_id: str, tool: Tool, args):
        yield self._emit({"type": "step", "id": call_id, "tool": tool.name, "label": tool.describe_call(args),
                          "status": "running"})
        started = time.monotonic()
        result, ok = execute(tool, self.ctx, args)
        yield self._emit({"type": "step", "id": call_id, "tool": tool.name, "label": tool.describe_call(args),
                          "status": "done" if ok else "error", "summary": summarize(result),
                          "ms": int((time.monotonic() - started) * 1000)})
        if ok and tool.ui:
            card = _ui_card(tool.ui, result)
            if card:
                yield self._emit(card)
        self._save_tool_result(call_id, tool.name, result)

    def _wrap_up(self):
        """Out of steps: ask for a summary of what was done and what's left, without more tools."""
        messages = self._model_messages() + [SystemMessage(
            "You have used all your steps for this turn. Don't call tools. Summarise what you found and "
            "did, and what's left (the user can say 'continue').")]
        try:
            ai = self.llm.invoke(messages)
            text = _text(ai.content) or "I've done as much as I can in one go. Say “continue” to keep going."
        except Exception as e:
            log.warning(f"Wrap-up failed: {e}")
            text = "I've done as much as I can in one go. Say “continue” to keep going."
        store.add_message(self.cid, "assistant", text)
        yield {"type": "token", "text": text}
        yield self._final(text)

    # --- memory ------------------------------------------------------------------------------

    def _model_messages(self) -> list:
        rows = store.messages(self.cid)
        if len(rows) > HISTORY_MESSAGES:
            start = len(rows) - HISTORY_MESSAGES
            while start < len(rows) - 1 and rows[start].role != "user":
                start += 1
            rows = rows[start:]
        last_user = max((i for i, r in enumerate(rows) if r.role == "user"), default=0)
        answered = {r.tool_call_id for r in rows if r.role == "tool"}
        name = self.ctx.actor
        out: list = [SystemMessage(prompts.system_prompt(self.ctx.role, name, self.subject_lines))]
        for i, r in enumerate(rows):
            if r.role == "user":
                out.append(HumanMessage(r.content))
            elif r.role == "assistant":
                calls = r.tool_calls or []
                out.append(AIMessage(content=r.content, tool_calls=[
                    {"id": c["id"], "name": c["name"], "args": c["args"], "type": "tool_call"} for c in calls]))
                for c in calls:  # a turn cut short (closed tab, crash): every call still needs a result
                    if c["id"] not in answered:
                        out.append(ToolMessage('{"error": "interrupted"}', tool_call_id=c["id"], name=c["name"]))
            elif r.role == "tool":
                limit = TOOL_RESULT_CHARS if i > last_user else OLD_TOOL_RESULT_CHARS
                content = r.content if len(r.content) <= limit else r.content[:limit] + " …(truncated)"
                out.append(ToolMessage(content, tool_call_id=r.tool_call_id, name=r.name or "tool"))
        return out

    def _save_tool_result(self, call_id: str, name: str, result: dict) -> None:
        content = json.dumps(result, default=str, ensure_ascii=False)
        if len(content) > STORED_RESULT_CHARS:
            content = content[:STORED_RESULT_CHARS]
        store.add_message(self.cid, "tool", content, tool_call_id=call_id, name=name)

    # --- answers -----------------------------------------------------------------------------

    def _final(self, text: str) -> dict:
        seen = self._seen_sources()
        valid, unverified = citations.check(citations.in_text(text), seen)
        cited = [seen[c] | {"text": seen[c]["text"][:600]} for c in valid]
        return self._emit({"type": "message", "text": text, "citations": cited, "unverified": unverified})

    def _seen_sources(self) -> dict[str, dict]:
        """Every passage / past question any tool returned in this conversation, by citation id."""
        seen: dict[str, dict] = {}
        for r in store.messages(self.cid):
            if r.role == "tool":
                try:
                    citations.collect(json.loads(r.content), seen)
                except ValueError:
                    continue
        return seen

    def _emit(self, event: dict) -> dict:
        self.turn_events.append(event)
        return event


def _text(content) -> str:
    if isinstance(content, str):
        return content
    if isinstance(content, list):  # content blocks
        return "".join(b.get("text", "") if isinstance(b, dict) else str(b) for b in content)
    return ""


def _ui_card(kind: str, result: dict) -> dict | None:
    if kind == "plan":
        return {"type": "plan", "steps": result.get("plan", [])}
    if kind == "quiz" and result.get("question"):
        return {"type": "quiz", "question": result["question"]}
    if kind == "answer":
        return {"type": "answer", **{k: result[k] for k in (
            "question_id", "correct", "your_choice", "correct_option", "explanation", "evidence_from_notes", "next_review")}}
    return None
