"""Faculty MCP server, through a real MCP client session (in-process), offline."""

import json
from datetime import date, timedelta

import anyio
import pytest
from mcp import Client
from starlette.testclient import TestClient

from tests.conftest import fresh_database
from langchain_core.messages import AIMessage, ToolMessage

from daily10 import auth, db, mcp_server, quality, retrieval, service
from daily10.assistant import subagents
from daily10.textproc import search_tokenize
from tests.test_study import NOTES, FakeLLM

PAGING_QUOTE = "The page table maps each page number to a frame number"


class ScriptedAgentModel:
    """A tool-calling model that replays sub-agent steps in order: each step is (tool, args).
    Records what it was sent, and the tool_choice it was bound with, so tests can check both."""

    def __init__(self, *steps):
        self.steps = list(steps)
        self.seen = []          # messages per call
        self.choices = []       # tool_choice per call

    def bind_tools(self, tools, tool_choice=None):
        model = self

        class Bound:
            def invoke(self, messages):
                model.choices.append(tool_choice)
                model.seen.append(list(messages))
                name, args = model.steps.pop(0) if model.steps else ("search_notes", {"subject": "CS501", "query": "again"})
                return AIMessage(content="", tool_calls=[{"id": f"s{len(model.seen)}", "name": name, "args": args,
                                                          "type": "tool_call"}])
        return Bound()


def tool_results(messages) -> str:
    return "\n".join(m.content for m in messages if isinstance(m, ToolMessage))


@pytest.fixture(autouse=True)
def seeded(monkeypatch):
    fresh_database()
    retrieval._cache.clear()
    monkeypatch.setattr(mcp_server, "_transport", "stdio")
    service.create_subject("cs501", "Operating Systems", "CSE", 5)
    service.add_notes("CS501", [("os_notes.pdf", NOTES * 3)])
    service.add_past_paper("CS501", "1. Explain the four necessary conditions for deadlock. (10 Marks)\n"
                                    "2. Explain paging and the role of the page table. (8 Marks)", 2024)
    service.generate_questions("CS501", FakeLLM())


def call(name, args=None):
    async def go():
        async with Client(mcp_server.mcp) as client:
            return await client.call_tool(name, args or {})
    return anyio.run(go)


def use_agent_model(monkeypatch, model):
    kinds = []
    monkeypatch.setattr(mcp_server, "_agent_model", lambda kind="main": kinds.append(kind) or model)
    return kinds


def a_passage_id(query):
    return retrieval.search_notes("CS501", query, top_k=1)[0]["id"]


# --- Tool listing ---------------------------------------------------------------------------

def test_tools_prompts_and_annotations():
    async def go():
        async with Client(mcp_server.mcp) as c:
            return (await c.list_tools()).tools, (await c.list_prompts()).prompts

    tools, prompts = anyio.run(go)
    tools = {t.name: t for t in tools}
    assert {"search_notes", "read_topic", "search_past_papers", "ask_notes", "review_question", "draft_questions",
            "class_insights", "set_question_status", "edit_question", "run_ai_check"} <= set(tools)
    assert tools["search_notes"].annotations.read_only_hint is True
    assert tools["set_question_status"].annotations.read_only_hint is False
    assert tools["ask_notes"].annotations.open_world_hint is True
    assert all(t.output_schema is not None for t in tools.values())
    assert {p.name for p in prompts} == {"review_queue", "class_report"}


# --- Data and retrieval ---------------------------------------------------------------------

def test_overview_and_list_questions():
    ov = call("subject_overview", {"subject": "cs501"}).structured_content
    assert ov["topics"] >= 2 and ov["past_paper_questions"] == 2
    assert ov["review_queue"]["drafts"] == ov["questions_by_status"]["draft"]

    qs = service.list_questions("CS501", "draft")
    service.set_question_status(qs[0]["id"], "draft", f"{quality.FLAGGED}: another option could also be correct")
    flagged = call("list_questions", {"subject": "CS501", "flagged_only": True}).structured_content
    assert flagged["total"] == 1 and flagged["questions"][0]["id"] == qs[0]["id"]
    by_topic = call("list_questions", {"subject": "CS501", "topic_id": qs[0]["topic_id"], "limit": 1}).structured_content
    assert by_topic["returned"] == 1 and by_topic["total"] >= 1


def test_search_notes_read_topic_and_past_papers():
    hits = call("search_notes", {"subject": "CS501", "query": "page table frame number", "top_k": 2}).structured_content
    top = hits["passages"][0]
    assert top["id"].startswith(f"T{top['topic_id']}#") and "page table" in top["content"].lower()

    topic = call("read_topic", {"topic_id": top["topic_id"]}).structured_content
    assert top["id"] in {p["id"] for p in topic["passages"]}

    past = call("search_past_papers", {"subject": "CS501", "query": "page tables"}).structured_content["questions"]
    assert past[0]["text"].startswith("Explain paging") and past[0]["year"] == 2024

    assert call("read_topic", {"topic_id": 99999}).is_error


def test_search_tokenizer_splits_identifiers_and_stems():
    tokens = search_tokenize("HorizontalPodAutoscaler startingDeadlineSeconds")
    assert {"horizontalpodautoscaler", "autoscal", "pod", "deadlin"} <= set(tokens)
    assert set(search_tokenize("autoscaling")) & set(tokens)


def test_class_insights_hides_codes_and_finds_behind_students():
    service.add_notes("CS501", [("unit2.pdf", NOTES * 3)])   # more topics than 2/day can cover in time
    student = service.register_student("Asha")
    today = date(2026, 11, 23)
    service.enroll(student.code, "CS501", exam_date=today + timedelta(days=3), start_date=today - timedelta(days=60))
    for q in service.list_questions("CS501", "draft"):
        service.set_question_status(q["id"], "approved")
    session = service.today_session(student.code, today)
    for q in session["questions"]:
        service.submit_answer(student.code, q["id"], 1, today)  # option 1 is wrong in the fake pack

    out = mcp_server.insights.class_insights("CS501", today)
    assert out["summary"]["students"] == 1 and out["summary"]["average_accuracy"] == 0.0
    row = out["students"][0]
    assert row["name"] == "Asha" and row["behind_schedule"] is True
    assert student.code not in json.dumps(out)


# --- Actions --------------------------------------------------------------------------------

def test_set_status_and_edit_question():
    q = service.list_questions("CS501", "draft")[0]
    res = call("set_question_status", {"question_id": q["id"], "status": "rejected"}).structured_content
    assert res["status"] == "rejected" and res["by"] == "local MCP client"
    assert call("set_question_status", {"question_id": q["id"], "status": "published"}).is_error

    bad = call("edit_question", {"question_id": q["id"], "evidence": "Something the notes never say at all"})
    assert bad.is_error and "evidence" in bad.content[0].text
    good = call("edit_question", {"question_id": q["id"], "prompt": "What does the page table map?",
                                  "options": ["Pages to frames", "Frames to disks", "Pages to processes", "Locks to threads"],
                                  "answer_index": 0, "evidence": PAGING_QUOTE}).structured_content
    assert good["status"] == "draft" and good["status_reason"].startswith("edited by")
    assert call("edit_question", {"question_id": q["id"], "options": ["A", "A", "B", "C"]}).is_error


def test_create_subject_rejects_duplicates():
    assert call("create_subject", {"code": "ma101", "name": "Maths"}).structured_content["code"] == "MA101"
    assert call("create_subject", {"code": "MA101", "name": "Maths"}).is_error


def test_add_notes_only_from_allowed_folders(tmp_path, monkeypatch):
    notes = tmp_path / "unit2.txt"
    notes.write_text(NOTES)
    monkeypatch.setenv("DAILY10_MCP_FILE_ROOTS", str(tmp_path / "uploads"))
    assert call("add_notes", {"subject": "CS501", "paths": [str(notes)]}).is_error

    monkeypatch.setenv("DAILY10_MCP_FILE_ROOTS", str(tmp_path))
    before = call("subject_overview", {"subject": "CS501"}).structured_content["topics"]
    res = call("add_notes", {"subject": "CS501", "paths": [str(notes)]}).structured_content
    assert res["topics_added"] >= 1
    assert call("subject_overview", {"subject": "CS501"}).structured_content["topics"] == before + res["topics_added"]


def test_file_tools_are_off_over_http_without_roots(monkeypatch, tmp_path):
    monkeypatch.delenv("DAILY10_MCP_FILE_ROOTS", raising=False)
    monkeypatch.setattr(mcp_server, "_transport", "streamable-http")
    (tmp_path / "p.txt").write_text("1. What is paging? (5 Marks)")
    res = call("add_past_paper", {"subject": "CS501", "path": str(tmp_path / "p.txt")})
    assert res.is_error and "DAILY10_MCP_FILE_ROOTS" in res.content[0].text


# --- Agents ---------------------------------------------------------------------------------

def test_ask_notes_searches_then_answers_with_verified_citations(monkeypatch):
    pid = a_passage_id("page table maps page number frame")
    model = ScriptedAgentModel(
        ("search_notes", {"subject": "CS501", "query": "page table maps page number frame"}),
        ("search_past_papers", {"subject": "CS501", "query": "paging"}),
        ("submit", {"answer": f"It maps pages to frames [{pid}].", "citations": [pid, "T999#0"],
                    "answered_from_notes": True, "confidence": "high"}),
    )
    kinds = use_agent_model(monkeypatch, model)
    out = call("ask_notes", {"subject": "CS501", "question": "What does the page table do?"}).structured_content
    assert out["citations"] == [pid] and out["invalid_citations"] == ["T999#0"]
    assert out["answered_from_notes"] is True and out["confidence"] == "high"
    assert out["sources"][0]["id"] == pid and len(out["steps"]) == 2
    assert out["steps"][0].startswith("Searching CS501 notes")
    assert pid in tool_results(model.seen[1])     # the model saw the retrieved passage before answering
    assert kinds == ["main"] and model.choices[0] == "required"


def test_ask_notes_without_valid_citations_is_low_confidence(monkeypatch):
    use_agent_model(monkeypatch, ScriptedAgentModel(("submit", {"answer": "From memory.", "citations": ["T1#0"],
                                                                "answered_from_notes": True, "confidence": "high"})))
    out = call("ask_notes", {"subject": "CS501", "question": "?"}).structured_content
    assert out["citations"] == [] and out["answered_from_notes"] is False and out["confidence"] == "low"


def test_subagent_fixes_bad_output_and_stays_in_its_subject(monkeypatch):
    model = ScriptedAgentModel(
        ("search_notes", {"subject": "MA101", "query": "limits"}),                     # another subject
        ("submit", {"answer": "x", "answered_from_notes": True, "confidence": "very"}),  # invalid output
        ("submit", {"answer": "Not in the notes.", "answered_from_notes": False, "confidence": "low"}),
    )
    use_agent_model(monkeypatch, model)
    out = call("ask_notes", {"subject": "CS501", "question": "?"}).structured_content
    assert out["answer"] == "Not in the notes."
    assert "isn't one of your subjects" in tool_results(model.seen[1])
    assert "Invalid arguments (confidence" in tool_results(model.seen[2])


def test_subagent_skips_repeats_and_forces_a_submit():
    ctx = subagents.Context(role="faculty", actor="t", owner_id=0)
    search = ("search_notes", {"subject": "CS501", "query": "deadlock"})
    model = ScriptedAgentModel(search, search, search, ("submit", {"answer": "done", "answered_from_notes": False,
                                                                    "confidence": "low"}))
    ctx.model_factory = lambda kind: model
    spec = subagents.AgentSpec(name="test", instructions="", output=subagents.ResearchOutput, max_steps=3)
    result = subagents.run(spec, "task", ctx, "CS501")
    assert result.output.answer == "done"
    assert result.steps.count("repeated call skipped") == 2
    assert model.choices[-1] == "submit" and "no steps left" in model.seen[-1][-1].content

    ctx.model_factory = lambda kind: ScriptedAgentModel()
    with pytest.raises(subagents.AgentError):
        subagents.run(spec.__class__(**{**spec.__dict__, "max_steps": 1}), "task", ctx, "CS501")


def test_review_question_runs_on_the_judge_model_and_keeps_only_grounded_edits(monkeypatch):
    q = service.list_questions("CS501", "draft")[0]
    first = retrieval.read_topic(q["topic_id"])["passages"][0]
    pid, quote = first["id"], " ".join(first["content"].split()[:12])
    edit = {"prompt": "Which is one of the four necessary conditions for deadlock?",
            "options": ["Circular wait", "Paging", "Caching", "Hashing"], "answer_index": 0,
            "explanation": "Circular wait is one of them.", "evidence": quote}
    kinds = use_agent_model(monkeypatch, ScriptedAgentModel(
        ("search_notes", {"subject": "CS501", "query": "deadlock conditions"}),
        ("submit", {"recommendation": "edit", "issues": ["vague wording"], "reasoning": f"See [{pid}].",
                    "citations": [pid], "suggested_edit": edit})))
    out = call("review_question", {"question_id": q["id"]}).structured_content
    assert kinds == ["judge"]
    assert out["recommendation"] == "edit" and out["citations"] == [pid]
    assert out["suggested_edit"]["evidence"] == quote and out["suggested_edit_dropped"] is None
    assert service.list_questions("CS501", "draft")  # nothing was changed by the review

    use_agent_model(monkeypatch, ScriptedAgentModel(("submit", {
        "recommendation": "edit", "issues": [], "reasoning": "", "citations": [],
        "suggested_edit": edit | {"evidence": "A sentence that the lecture notes do not contain"}})))
    out = call("review_question", {"question_id": q["id"]}).structured_content
    assert out["suggested_edit"] is None and "evidence" in out["suggested_edit_dropped"]


def test_draft_questions_saves_grounded_drafts_under_the_cited_topic(monkeypatch):
    pid = a_passage_id("page table maps page number frame")
    topic_id = int(pid[1:].split("#")[0])
    good = {"prompt": "What does a page table map each page number to?", "options": ["A frame number", "A disk block",
            "A process id", "A cache line"], "answer_index": 0, "explanation": "Stated in the notes.",
            "evidence": PAGING_QUOTE, "citation": pid}
    ungrounded = good | {"prompt": "What is a TLB?", "evidence": "A TLB caches recent page table lookups in hardware"}
    uncited = good | {"prompt": "Unretrieved?", "citation": "T999#1"}
    use_agent_model(monkeypatch, ScriptedAgentModel(
        ("search_notes", {"subject": "CS501", "query": "page table maps page number frame"}),
        ("submit", {"questions": [good, ungrounded, uncited]})))
    out = call("draft_questions", {"subject": "CS501", "focus": "paging", "n": 3}).structured_content
    statuses = {c["prompt"]: (c["status"], c["topic_id"]) for c in out["created"]}
    assert statuses[good["prompt"]] == ("draft", topic_id)
    assert statuses["What is a TLB?"][0] == "auto_rejected"
    assert len(out["discarded"]) == 1 and "T999#1" in out["discarded"][0]


def test_agent_tools_report_missing_llm_key(monkeypatch):
    def no_key(kind="main"):
        raise RuntimeError("Set GROQ_API_KEY in .env")
    monkeypatch.setattr(mcp_server, "_agent_model", no_key)
    res = call("ask_notes", {"subject": "CS501", "question": "x"})
    assert res.is_error and "GROQ_API_KEY" in res.content[0].text


# --- HTTP auth ------------------------------------------------------------------------------

INIT = {"jsonrpc": "2.0", "id": 1, "method": "initialize",
        "params": {"protocolVersion": "2025-06-18", "capabilities": {}, "clientInfo": {"name": "t", "version": "1"}}}
HEADERS = {"accept": "application/json, text/event-stream", "content-type": "application/json"}


def test_http_requires_faculty_token_or_admin_key(monkeypatch):
    monkeypatch.setenv("STUDY_ADMIN_KEY", "uni-key")
    auth.register("Dr Rao", "rao@uni.edu", "a-long-password", "uni-key")
    token, _ = auth.login("rao@uni.edu", "a-long-password")
    assert mcp_server.actor_for_token(token) == "Dr Rao"
    assert mcp_server.actor_for_token("uni-key") == "university admin key"
    assert mcp_server.actor_for_token("wrong") is None

    with TestClient(mcp_server.http_app(), base_url="http://127.0.0.1:8765") as client:
        assert client.post("/mcp", json=INIT, headers=HEADERS).status_code == 401
        assert client.post("/mcp", json=INIT, headers=HEADERS | {"authorization": "Bearer nope"}).status_code == 401
        ok = client.post("/mcp", json=INIT, headers=HEADERS | {"authorization": f"Bearer {token}"})
        assert ok.status_code == 200 and ok.json()["result"]["serverInfo"]["name"] == "daily10-faculty"
