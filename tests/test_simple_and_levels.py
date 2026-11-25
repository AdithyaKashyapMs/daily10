"""The "explain simply" layer, question levels and the warm-up -> core -> exam ladder (offline)."""

import json
from datetime import date, timedelta

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, inspect, text

from daily10 import db, scheduler, service
from tests.conftest import fresh_database
from tests.test_study import NOTES


class LevelledLLM:
    """JSON-mode LLM: a full topic pack with a simple layer and one question per level."""

    def __init__(self, simple=True):
        self.simple, self.prompts = simple, []

    def invoke(self, prompt):
        self.prompts.append(prompt)
        notes = prompt.split("NOTES:\n", 1)[1]
        quote = " ".join(notes.split()[:12])
        q = {"options": ["Circular wait", "Paging", "Caching", "Hashing"], "answer_index": 0,
             "explanation": "Circular wait is one of the four conditions of a deadlock.", "evidence": quote}
        layer = {"simple_explanation": "Processes get stuck waiting for each other, like cars at a jammed crossing.",
                 "analogy": "Four cars at a crossing, each waiting for the next to move.",
                 "glossary": [{"term": "deadlock", "meaning": "everyone waits forever"},
                              {"term": "mutex lock", "meaning": "not in these notes"},      # dropped: not in notes
                              {"term": "Deadlock", "meaning": "duplicate"},                  # dropped: duplicate
                              {"term": "process"}]} if self.simple else {}                  # dropped: malformed
        pack = {"title": "Deadlocks", "summary": "Processes block each other.", "key_points": ["4 conditions"],
                "questions": [q | {"question": "Exam: which condition breaks here?", "level": "exam"},
                              q | {"question": "Core: why does it deadlock?", "level": "Core"},
                              q | {"question": "Warm-up: what is a deadlock?", "level": "warm-up"},
                              q | {"question": "Unlabelled?"}]} | layer

        class R:
            content = json.dumps(pack)
        return R()


@pytest.fixture(autouse=True)
def fresh():
    fresh_database()


def subject(llm=None, approve=True, approve_simple=True):
    service.create_subject("cs501", "Operating Systems", "CSE", 5)
    service.add_notes("CS501", [("os_notes.pdf", NOTES * 3)])
    service.generate_questions("CS501", llm or LevelledLLM())
    if approve:
        for q in service.list_questions("CS501", "draft"):
            service.set_question_status(q["id"], "approved")
    if approve_simple:
        for e in service.list_explanations("CS501", "draft"):
            service.review_explanation(e["topic_id"], "approved")


def student(day):
    st = service.register_student("Asha")
    service.enroll(st.code, "CS501", exam_date=day + timedelta(days=90), start_date=day)
    return st


# --- Generation ------------------------------------------------------------------------------

def test_generation_stores_levels_and_a_grounded_simple_layer_as_a_draft():
    subject(approve=False, approve_simple=False)
    qs = service.list_questions("CS501", "draft")
    assert {q["prompt"].split(":")[0]: q["level"] for q in qs if ":" in q["prompt"]} == {
        "Exam": "exam", "Core": "core", "Warm-up": "warmup"}
    assert next(q for q in qs if q["prompt"] == "Unlabelled?")["level"] == "core"

    ex = service.list_explanations("CS501")
    assert ex and all(e["status"] == "draft" for e in ex)
    assert [g["term"] for g in ex[0]["glossary"]] == ["deadlock"]       # ungrounded, duplicate, malformed dropped
    assert "simple_explanation" in LevelledLLM().invoke("NOTES:\nx").content


def test_older_topics_get_only_the_simple_layer_backfilled():
    subject(llm=LevelledLLM(simple=False), approve=False, approve_simple=False)
    assert service.list_explanations("CS501") == []
    before = len(service.list_questions("CS501"))

    llm = LevelledLLM()
    stats = service.generate_questions("CS501", llm, limit=1)
    assert stats["simple_explanations"] == 1 and stats["draft"] == 0
    assert all("simple_explanation" in p and '"key_points"' not in p for p in llm.prompts)   # not a full pack
    assert len(service.list_questions("CS501")) == before                 # no duplicate questions
    service.generate_questions("CS501", llm)
    assert len(service.list_explanations("CS501")) == len(service.topic_overview("CS501"))


def test_backfill_also_tags_existing_question_levels():
    subject(llm=LevelledLLM(simple=False), approve=False, approve_simple=False)
    topic_id = service.topic_overview("CS501")[0]["id"]
    ids = [q["id"] for q in service.list_questions("CS501") if q["topic_id"] == topic_id and q["status"] == "draft"]
    before = {q["id"]: q["level"] for q in service.list_questions("CS501")}

    class Tagger:
        def invoke(self, prompt):
            assert "QUESTIONS:" in prompt and f"{ids[0]}: " in prompt

            class R:
                content = json.dumps({"simple_explanation": "Stuck processes.", "analogy": "", "glossary": [],
                                      "levels": {str(ids[0]): "Warm-up", str(ids[1]): "exam", "99999": "exam",
                                                 str(ids[2]): "impossible"}})
            return R()

    stats = service.generate_questions("CS501", Tagger(), limit=1)
    assert stats["levels_tagged"] == 2 and stats["simple_explanations"] == 1
    levels = {q["id"]: q["level"] for q in service.list_questions("CS501")}
    assert (levels[ids[0]], levels[ids[1]]) == ("warmup", "exam")
    assert levels[ids[2]] == before[ids[2]]                            # an invalid level changes nothing


def test_faculty_can_edit_approve_and_reject_the_simple_layer():
    subject(approve_simple=False)
    topic_id = service.list_explanations("CS501")[0]["topic_id"]
    out = service.review_explanation(topic_id, "approved", {
        "analogy": "  Like a traffic jam.  ",
        "glossary": [{"term": "circular wait", "meaning": "each waits on the next"},
                     {"term": "quantum entanglement", "meaning": "not in the notes"}]})
    assert out["status"] == "approved" and out["analogy"] == "Like a traffic jam."
    assert [g["term"] for g in out["glossary"]] == ["circular wait"]
    assert service.review_explanation(topic_id, "rejected")["status"] == "rejected"
    with pytest.raises(ValueError):
        service.review_explanation(topic_id, "approved", {"title": "nope"})
    assert service.topic_overview("CS501")[0]["simple_status"] == "rejected"


# --- Students --------------------------------------------------------------------------------

def test_card_shows_the_simple_layer_only_once_approved_even_mid_day():
    subject(approve_simple=False)
    day = date.today()
    st = student(day)
    card = service.today_session(st.code, day)["card"]
    assert card["simple"] is None and card["start_simple"] is False

    service.review_explanation(card["topic_id"], "approved")
    card = service.today_session(st.code, day)["card"]                  # same day, plan already built
    assert card["simple"]["analogy"].startswith("Four cars") and card["simple"]["glossary"][0]["term"] == "deadlock"


def test_wrong_answers_get_the_simple_explanation_with_the_terms_they_used():
    subject()
    day = date.today()
    st = student(day)
    qs = service.today_session(st.code, day)["questions"]
    wrong = service.submit_answer(st.code, qs[0]["id"], 1, day)
    assert not wrong["correct"]
    assert wrong["simple"]["explanation"].startswith("Processes get stuck")
    assert [g["term"] for g in wrong["simple"]["glossary"]] == ["deadlock"]   # "deadlock" is in the explanation
    right = service.submit_answer(st.code, qs[1]["id"], 0, day)
    assert right["correct"] and right["simple"] is None


def test_session_climbs_the_ladder_and_confident_students_skip_the_warmup():
    subject()
    day = date.today()
    st = student(day)
    s1 = service.today_session(st.code, day)
    assert [q["level"] for q in s1["questions"]] == ["warmup", "core", "exam"]   # easiest first
    assert all(q["kind"] == "new" for q in s1["questions"])

    # Two days of all-correct answers (6, the minimum to judge): "confident" in CS501 on day 3.
    for d in range(2):
        for q in service.today_session(st.code, day + timedelta(days=d))["questions"]:
            service.submit_answer(st.code, q["id"], 0, day + timedelta(days=d))
    new = [q for q in service.today_session(st.code, day + timedelta(days=2))["questions"] if q["kind"] == "new"]
    assert [q["level"] for q in new] == ["core", "core", "exam"]          # no warm-up; still climbs


def test_struggling_students_start_on_the_simple_card():
    subject()
    day = date.today()
    st = student(day)
    assert service.today_session(st.code, day)["card"]["start_simple"] is False     # too early to tell
    for d in range(2):
        for q in service.today_session(st.code, day + timedelta(days=d))["questions"]:
            service.submit_answer(st.code, q["id"], 1, day + timedelta(days=d))    # always wrong
    s3 = service.today_session(st.code, day + timedelta(days=2))
    assert s3["card"]["start_simple"] is True and s3["card"]["simple"] is not None
    assert [q["level"] for q in s3["questions"] if q["kind"] == "new"] == ["warmup", "core", "exam"]


def test_ladder_and_bands_are_pure_functions():
    assert scheduler.learner_band(5, 0) == "steady"           # too early to tell
    assert scheduler.learner_band(10, 5) == "struggling"
    assert scheduler.learner_band(10, 7) == "steady"
    assert scheduler.learner_band(20, 18) == "confident"
    pool = [(1, "exam"), (2, "warmup"), (3, "core"), (4, "warmup")]
    assert scheduler.pick_new_questions(pool, "steady") == [2, 3, 1]
    assert scheduler.pick_new_questions(pool, "confident") == [2, 3, 1]   # one exam question: a warm-up fills in
    assert scheduler.pick_new_questions([(3, "core"), (5, "exam"), (6, "exam"), (2, "warmup")], "confident") == [3, 5, 6]
    assert scheduler.pick_new_questions([(7, "core")], "steady") == [7]
    assert scheduler.pick_new_questions([], "steady") == []


# --- API and migration -------------------------------------------------------------------------

def test_faculty_api_for_levels_and_explanations():
    from daily10 import main

    subject(approve_simple=False)
    client = TestClient(main.app)
    ex = client.get("/study/subjects/CS501/explanations?status=draft").json()
    assert ex and ex[0]["status"] == "draft"
    ok = client.post(f"/study/topics/{ex[0]['topic_id']}/explanation",
                     json={"status": "approved", "analogy": "Like a jam."}).json()
    assert ok["status"] == "approved" and ok["analogy"] == "Like a jam."
    assert client.post(f"/study/topics/{ex[0]['topic_id']}/explanation", json={"status": "live"}).status_code == 422
    assert client.post("/study/topics/99999/explanation", json={"status": "approved"}).status_code == 404

    qid = service.list_questions("CS501")[0]["id"]
    assert client.post(f"/study/questions/{qid}/level", json={"level": "exam"}).json()["level"] == "exam"
    assert client.post(f"/study/questions/{qid}/level", json={"level": "hard"}).status_code == 422


def test_existing_databases_get_the_new_columns(tmp_path):
    url = f"sqlite:///{tmp_path / 'old.sqlite'}"
    db.init(url)
    engine = create_engine(url)
    with engine.begin() as conn:
        for table, col in (("topics", "glossary"), ("topics", "simple_status"), ("questions", "level")):
            conn.execute(text(f"ALTER TABLE {table} DROP COLUMN {col}"))
    db.init(url)
    cols = {c["name"] for c in inspect(engine).get_columns("topics")}
    assert {"simple_explanation", "analogy", "glossary", "simple_status"} <= cols
    assert "level" in {c["name"] for c in inspect(engine).get_columns("questions")}
    fresh_database()
