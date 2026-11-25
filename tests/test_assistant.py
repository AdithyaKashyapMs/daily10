"""In-app assistant: agent loop, tools, approvals, citations, memory and the SSE API (offline)."""

import json
from datetime import date, timedelta

import pytest
from fastapi.testclient import TestClient
from langchain_core.messages import AIMessage, ToolMessage

from daily10 import auth, db, retrieval, service, student_auth
from daily10.assistant import Assistant, Context, engine, store
from daily10.db import Review
from tests.conftest import fresh_database
from tests.test_mcp_server import ScriptedAgentModel
from tests.test_study import NOTES, FakeLLM


class ToolLLM:
    """Scripted chat model with tool calling. Each step: a string (final text) or a list of (tool, args)."""

    def __init__(self, *steps, fail=False):
        self.steps, self.fail, self.seen = list(steps), fail, []

    def _next(self, messages):
        self.seen.append(messages)
        if self.fail:
            raise RuntimeError("rate limited")
        step = self.steps.pop(0) if self.steps else "Done."
        if isinstance(step, str):
            return AIMessage(content=step)
        return AIMessage(content="", tool_calls=[{"id": f"c{len(self.seen)}_{i}", "name": n, "args": a, "type": "tool_call"}
                                                 for i, (n, a) in enumerate(step)])

    def stream(self, messages):
        yield self._next(messages)

    def invoke(self, messages):
        return self._next(messages)


@pytest.fixture(autouse=True)
def seeded():
    fresh_database()
    retrieval._cache.clear()
    service.create_subject("cs501", "Operating Systems", "CSE", 5)
    service.add_notes("CS501", [("os_notes.pdf", NOTES * 3)])
    service.add_past_paper("CS501", "1. Explain the four necessary conditions for deadlock. (10 Marks)", 2024)
    service.generate_questions("CS501", FakeLLM())
    for q in service.list_questions("CS501", "draft"):
        service.set_question_status(q["id"], "approved")
    service.create_subject("ma101", "Maths", "MA", 1)


def student_ctx(name="Asha", email="asha@uvce.ac.in", enroll=True) -> Context:
    s = service.register_student(name, "19:00", email=email)
    if enroll:
        service.enroll(s.code, "CS501", date.today() + timedelta(days=60), date.today())
    return Context(role="student", actor=s.name, owner_id=s.id, student_code=s.code)


def faculty_ctx(model_factory=None) -> Context:
    return Context(role="faculty", actor="Dr Rao", owner_id=1, model_factory=model_factory)


def run(ctx, llm, message, conversation_id=None):
    cid = conversation_id or store.create_conversation(ctx.role, ctx.owner_id, message).id
    events = list(Assistant(ctx, cid, llm).chat(message))
    return cid, events


def of(events, kind):
    return [e for e in events if e["type"] == kind]


def passage_id(query="page table maps page number frame"):
    return retrieval.search_notes("CS501", query, top_k=1)[0]["id"]


# --- Agent loop, RAG and citations ----------------------------------------------------------

def test_plans_searches_and_answers_with_checked_citations():
    ctx = student_ctx()
    pid = passage_id()
    llm = ToolLLM(
        [("update_plan", {"steps": [{"title": "Search the notes", "status": "in_progress"}, {"title": "Explain", "status": "pending"}]})],
        [("search_notes", {"subject": "cs501", "query": "page table maps page number frame"})],
        f"The page table maps pages to frames [{pid}]. Also see [T999#0].",
    )
    cid, events = run(ctx, llm, "What does a page table do?")

    assert of(events, "plan")[0]["steps"][0]["title"] == "Search the notes"
    steps = [e for e in of(events, "step") if e["status"] == "done"]
    assert steps[1]["label"] == "Searching CS501 notes for “page table maps page number frame”"
    final = of(events, "message")[0]
    assert [c["id"] for c in final["citations"]] == [pid] and final["unverified"] == ["T999#0"]
    assert "page table" in final["citations"][0]["text"].lower()
    assert any(e["type"] == "token" for e in events)

    # The model saw the tool result before answering, and the turn was saved for reopening.
    assert any(isinstance(m, ToolMessage) and pid in m.content for m in llm.seen[2])
    saved = store.messages(cid)
    assert [m.role for m in saved] == ["user", "assistant", "tool", "assistant", "tool", "assistant"]
    assert {e["type"] for e in saved[0].events} >= {"plan", "step", "message"}


def test_students_only_search_their_own_subjects():
    ctx = student_ctx()
    llm = ToolLLM([("search_notes", {"subject": "MA101", "query": "limits"})], "That isn't one of your subjects.")
    _, events = run(ctx, llm, "Search maths")
    err = [e for e in of(events, "step") if e["status"] == "error"][0]
    assert "isn't one of your subjects" in err["summary"]


def test_quiz_never_shows_the_answer_and_answers_feed_spaced_repetition():
    ctx = student_ctx()
    service.today_session(ctx.student_code)  # learn the first topic
    llm = ToolLLM([("quiz_me", {"mode": "new"})], "Here's one! Pick an option.")
    cid, events = run(ctx, llm, "Quiz me")
    quiz = of(events, "quiz")[0]["question"]
    tool_result = json.loads(store.messages(cid)[2].content)
    assert "answer_index" not in json.dumps(tool_result) and "evidence" not in json.dumps(tool_result)
    assert quiz["options"][0].startswith("A. ")

    llm = ToolLLM([("check_answer", {"question_id": quiz["question_id"], "choice": "My answer: B"})], "Not quite!")
    _, events = run(ctx, llm, "My answer: B", cid)
    card = of(events, "answer")[0]
    assert card["correct"] is False and card["correct_option"].startswith("A.") and card["your_choice"] == "B"
    with db.session() as s:
        r = s.query(Review).filter_by(question_id=quiz["question_id"]).one()
        assert r.attempts == 1 and r.correct == 0 and r.due_on == date.today() + timedelta(days=1)


def test_invalid_arguments_go_back_to_the_model_which_fixes_them():
    ctx = student_ctx()
    llm = ToolLLM([("search_notes", {"query": "deadlock"})],                       # missing subject
                  [("search_notes", {"subject": "CS501", "query": "deadlock"})], "Fixed it.")
    _, events = run(ctx, llm, "deadlock?")
    assert [e["status"] for e in of(events, "step")] == ["error", "running", "done"]
    error_result = [m for m in llm.seen[1] if isinstance(m, ToolMessage)][0].content
    assert "subject" in error_result and "Field required" in error_result


def test_tools_are_scoped_to_the_role():
    ctx = student_ctx()
    qid = service.list_questions("CS501", "approved")[0]["id"]
    llm = ToolLLM([("set_question_status", {"question_ids": [qid], "status": "rejected"})], "I can't do that.")
    _, events = run(ctx, llm, "Reject that question")
    assert not of(events, "confirm")
    assert "no tool called set_question_status" in [m for m in llm.seen[1] if isinstance(m, ToolMessage)][0].content
    assert service.list_questions("CS501", "approved")


# --- Approvals --------------------------------------------------------------------------------

def test_changes_wait_for_approval_then_continue():
    ctx = student_ctx()
    llm = ToolLLM([("set_reminder_time", {"time": "20:30"})], "Done! Reminders at 8:30 pm.")
    cid, events = run(ctx, llm, "Remind me at 8:30pm")
    confirm = of(events, "confirm")[0]
    assert confirm["summary"] == "Change your daily reminder to 20:30" and of(events, "waiting")
    assert service.student_profile(ctx.student_code)["notify_time"] == "19:00"   # not yet

    events = list(Assistant(ctx, cid, llm).resolve(confirm["action_id"], approve=True))
    assert of(events, "confirm_resolved")[0]["status"] == "approved"
    assert service.student_profile(ctx.student_code)["notify_time"] == "20:30"
    assert of(events, "message")[0]["text"].startswith("Done!")
    with pytest.raises(ValueError, match="already decided"):
        list(Assistant(ctx, cid, llm).resolve(confirm["action_id"], approve=True))


def test_declined_and_ignored_changes_are_not_made():
    ctx = student_ctx()
    llm = ToolLLM([("set_reminder_time", {"time": "06:00"})], "OK, I left it as it was.")
    cid, events = run(ctx, llm, "Remind me at 6")
    list(Assistant(ctx, cid, llm).resolve(of(events, "confirm")[0]["action_id"], approve=False))
    assert service.student_profile(ctx.student_code)["notify_time"] == "19:00"
    assert "chose not to" in [m for m in llm.seen[-1] if isinstance(m, ToolMessage)][-1].content

    llm = ToolLLM([("set_reminder_time", {"time": "07:00"})], "Never mind.")
    cid, events = run(ctx, llm, "Remind me at 7")
    llm2 = ToolLLM("Sure, what next?")
    events2 = list(Assistant(ctx, cid, llm2).chat("Actually, forget it"))
    assert of(events2, "message") and service.student_profile(ctx.student_code)["notify_time"] == "19:00"
    assert not store.open_pending(cid)
    assert "sent a new message instead" in [m for m in llm2.seen[0] if isinstance(m, ToolMessage)][-1].content


def test_only_one_change_waits_at_a_time():
    ctx = student_ctx()
    llm = ToolLLM([("set_reminder_time", {"time": "20:00"}), ("enroll_subject", {"subject_code": "MA101",
                   "exam_date": str(date.today() + timedelta(days=30))})])
    cid, events = run(ctx, llm, "Remind me at 8 and add maths")
    assert len(of(events, "confirm")) == 1
    second = json.loads([m for m in store.messages(cid) if m.role == "tool"][0].content)
    assert "waiting for the user's approval" in second["error"]


def test_faculty_batch_approval():
    drafts = [q["id"] for q in service.list_questions("CS501", "approved")][:2]
    for qid in drafts:
        service.set_question_status(qid, "draft")
    ctx = faculty_ctx()
    llm = ToolLLM([("set_question_status", {"question_ids": drafts, "status": "approved"})], "Approved both.")
    cid, events = run(ctx, llm, "Approve them")
    assert of(events, "confirm")[0]["summary"] == f"Approve 2 questions: #{drafts[0]}, #{drafts[1]}"
    list(Assistant(ctx, cid, llm).resolve(of(events, "confirm")[0]["action_id"], approve=True))
    assert {q["id"] for q in service.list_questions("CS501", "approved")} >= set(drafts)


# --- Sub-agents, limits and failures ----------------------------------------------------------

def test_copilot_hands_a_question_to_the_reviewer_subagent():
    q = service.list_questions("CS501", "approved")[0]
    first = retrieval.read_topic(q["topic_id"])["passages"][0]
    reviewer = ScriptedAgentModel(("search_notes", {"subject": "CS501", "query": "deadlock"}),
                                  ("submit", {"recommendation": "approve", "issues": [], "citations": [first["id"]],
                                              "reasoning": f"Supported by [{first['id']}]."}))
    used = []
    ctx = faculty_ctx(lambda kind: used.append(kind) or reviewer)
    llm = ToolLLM([("review_question", {"question_id": q["id"]})], f"The reviewer recommends approving it [{first['id']}].")
    _, events = run(ctx, llm, "Check that question")
    step = [e for e in of(events, "step") if e["status"] == "done"][0]
    assert step["summary"] == "recommends: approve" and used == ["judge"]
    assert of(events, "message")[0]["citations"][0]["id"] == first["id"]


def test_step_limit_wraps_up(monkeypatch):
    monkeypatch.setattr(engine, "MAX_STEPS", 3)
    ctx = student_ctx()
    llm = ToolLLM(*[[("my_overview", {})]] * 3, "Here's what I found so far.")
    _, events = run(ctx, llm, "Loop forever")
    assert len([e for e in of(events, "step") if e["status"] == "done"]) == 3
    assert of(events, "message")[0]["text"] == "Here's what I found so far."


def test_model_outage_is_reported():
    _, events = run(student_ctx(), ToolLLM(fail=True), "Hi")
    assert of(events, "error")[0]["message"].startswith("The AI service is busy")


def test_interrupted_turns_are_repaired_and_old_results_shortened():
    ctx = student_ctx()
    cid = store.create_conversation("student", ctx.owner_id, "x").id
    store.add_message(cid, "user", "earlier")
    store.add_message(cid, "assistant", "", tool_calls=[{"id": "lost", "name": "my_overview", "args": {}},
                                                        {"id": "kept", "name": "get_today", "args": {}}])
    store.add_message(cid, "tool", json.dumps({"big": "x" * 5000}), tool_call_id="kept", name="get_today")
    llm = ToolLLM("Hello again.")
    list(Assistant(ctx, cid, llm).chat("hi"))
    sent = {m.tool_call_id: m.content for m in llm.seen[0] if isinstance(m, ToolMessage)}
    assert sent["lost"] == '{"error": "interrupted"}'
    assert len(sent["kept"]) < 700 and sent["kept"].endswith("(truncated)")


# --- API --------------------------------------------------------------------------------------

def sse(response) -> list[dict]:
    return [json.loads(line[6:]) for line in response.text.splitlines() if line.startswith("data: ")]


@pytest.fixture
def client(monkeypatch):
    from daily10 import llm, main

    scripts = []
    monkeypatch.setattr(llm, "get_tool_llm", lambda tools, temperature=0.0: scripts.pop(0))
    c = TestClient(main.app)
    c.scripts = scripts
    return c


def student_headers(email="asha@uvce.ac.in"):
    ctx = student_ctx(email=email, name=email.split("@")[0])
    return ctx, {"Authorization": f"Bearer {student_auth.issue_token(ctx.owner_id)}"}


def test_api_streams_a_turn_and_reopens_it(client):
    ctx, h = student_headers()
    client.scripts.append(ToolLLM([("my_overview", {})], "You're on track!"))
    events = sse(client.post("/study/assistant/chat", json={"message": "How am I doing?"}, headers=h))
    assert [e["type"] for e in events][0] == "conversation" and events[-1]["type"] == "done"
    cid = events[0]["id"]
    assert of(events, "message")[0]["text"] == "You're on track!"

    convo = client.get(f"/study/assistant/conversations/{cid}", headers=h).json()
    assert convo["turns"][0]["message"] == "How am I doing?"
    assert [e["type"] for e in convo["turns"][0]["events"]] == ["step", "step", "message"]
    assert client.get("/study/assistant/conversations", headers=h).json()[0]["id"] == cid
    assert client.get("/study/assistant/starters", headers=h).json()[0]["title"] == "Explain today's topic"


def test_api_approval_over_sse(client):
    ctx, h = student_headers()
    client.scripts.append(ToolLLM([("set_reminder_time", {"time": "21:00"})]))
    events = sse(client.post("/study/assistant/chat", json={"message": "9pm reminders"}, headers=h))
    cid, action = events[0]["id"], of(events, "confirm")[0]["action_id"]
    assert client.get(f"/study/assistant/conversations/{cid}", headers=h).json()["pending"] == [action]
    client.scripts.append(ToolLLM("Set for 9 pm."))
    events = sse(client.post(f"/study/assistant/conversations/{cid}/actions/{action}", json={"approve": True}, headers=h))
    assert of(events, "message")[0]["text"] == "Set for 9 pm."
    assert service.student_profile(ctx.student_code)["notify_time"] == "21:00"
    again = client.post(f"/study/assistant/conversations/{cid}/actions/{action}", json={"approve": True}, headers=h)
    assert again.status_code == 409


def test_api_conversations_are_private_and_rate_limited(client, monkeypatch):
    _, asha = student_headers("asha@uvce.ac.in")
    _, ravi = student_headers("ravi@uvce.ac.in")
    client.scripts.append(ToolLLM("Hi Asha."))
    cid = sse(client.post("/study/assistant/chat", json={"message": "hi"}, headers=asha))[0]["id"]
    assert client.get(f"/study/assistant/conversations/{cid}", headers=ravi).status_code == 404
    assert client.post("/study/assistant/chat", json={"message": "hi", "conversation_id": cid}, headers=ravi).status_code == 404
    assert client.delete(f"/study/assistant/conversations/{cid}", headers=ravi).status_code == 404
    assert client.post("/study/assistant/chat", json={"message": "hi"}).status_code == 401

    from daily10 import assistant_api
    monkeypatch.setattr(assistant_api, "MAX_MESSAGES_PER_HOUR", 1)
    assert client.post("/study/assistant/chat", json={"message": "again"}, headers=asha).status_code == 429
    assert client.delete(f"/study/assistant/conversations/{cid}", headers=asha).status_code == 200


def test_api_faculty_gets_the_copilot(client, monkeypatch):
    monkeypatch.setenv("STUDY_ADMIN_KEY", "k")
    auth.register("Dr Rao", "rao@uvce.ac.in", "a-long-password", "k")
    token, _ = auth.login("rao@uvce.ac.in", "a-long-password")
    h = {"Authorization": f"Bearer {token}"}
    assert "CS501" in client.get("/study/assistant/starters", headers=h).json()[0]["prompt"]
    client.scripts.append(ToolLLM([("class_insights", {"subject": "CS501"})], "Report ready."))
    events = sse(client.post("/study/assistant/chat", json={"message": "class report"}, headers=h))
    assert [e for e in of(events, "step") if e["status"] == "done"][0]["label"] == "Analysing the CS501 class"
