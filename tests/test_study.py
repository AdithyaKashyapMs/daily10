import json
from datetime import date, timedelta

import pytest
from fastapi.testclient import TestClient

from daily10 import content, db, generate, notify, scheduler, service

NOTES = (
    "A deadlock is a situation where a set of processes are blocked because each process is holding a "
    "resource and waiting for another resource held by another process. The four necessary conditions are "
    "mutual exclusion, hold and wait, no preemption and circular wait. " * 4
    + "\n\nThe Banker's algorithm avoids deadlock by checking whether granting a request leaves the system "
    "in a safe state. A safe state is one where there exists a sequence in which every process can finish. " * 4
    + "\n\nPaging divides physical memory into fixed-size frames and logical memory into pages of the same "
    "size. The page table maps each page number to a frame number. " * 4
)


class FakeLLM:
    """JSON-mode LLM: returns a pack whose evidence quotes come from the prompt's notes."""

    def __init__(self, bad_evidence=False):
        self.bad = bad_evidence

    def invoke(self, prompt):
        notes = prompt.split("NOTES:\n", 1)[1]
        quote = "This sentence is not anywhere in the notes at all" if self.bad else " ".join(notes.split()[:12])
        q = {"question": "Which is a necessary condition for deadlock?", "options": ["Circular wait", "Paging", "Caching", "Hashing"],
             "answer_index": 0, "explanation": "Circular wait is one of the four conditions.", "evidence": quote}
        broken = {"question": "Broken", "options": ["A", "A"], "answer_index": 7, "explanation": "", "evidence": quote}

        class R:
            content = json.dumps({"title": "Deadlocks", "summary": "Processes block each other.",
                                  "key_points": ["4 conditions", "Banker's algorithm"], "questions": [q, q | {"question": "Q2?"}, broken]})
        return R()


@pytest.fixture(autouse=True)
def fresh_db():
    db.init("sqlite://")
    yield


def make_subject(topics_text=NOTES * 3, approve=True):  # ~3 topics
    service.create_subject("cs501", "Operating Systems", "CSE", 5)
    service.add_notes("CS501", [("os_notes.pdf", topics_text)])
    service.generate_questions("CS501", FakeLLM())
    if approve:
        for q in service.list_questions("CS501", "draft"):
            service.set_question_status(q["id"], "approved")


# --- content ---------------------------------------------------------------------------------

def test_notes_split_into_ordered_topics():
    topics = content.split_into_topics(NOTES, "os.pdf", target_chars=1200)
    assert len(topics) >= 2 and topics[0]["source"] == "os.pdf, part 1"
    assert "deadlock" in topics[0]["text"].lower()


def test_past_paper_parsing():
    paper = """VTU Exam 2023
1. a) Explain the four necessary conditions for deadlock. (10 Marks)
   b) Describe the Banker's algorithm with an example. (10 Marks)
2. Explain paging and the role of the page table. 8M
Q3 What is a safe state?"""
    qs = content.split_past_paper(paper)
    assert [q["marks"] for q in qs] == [10, 10, 8, None]
    assert qs[0]["text"].startswith("Explain the four necessary conditions")
    assert content.year_from_name("os_paper_2023_june.pdf") == 2023


def test_past_questions_match_topics_and_set_weight():
    make_subject(approve=False)
    service.add_past_paper("CS501", "1. Explain paging and the page table frame mapping. (10 Marks)\n"
                                    "2. What is a safe state in the Banker's algorithm? (5 Marks)", 2023)
    weights = {t["title"] or t["source"]: t["exam_weight"] for t in service.topic_overview("CS501")}
    assert sum(weights.values()) == 2


# --- generation and grounding ----------------------------------------------------------------

def test_evidence_check():
    assert generate.evidence_found("each process is holding a resource", NOTES)
    assert generate.evidence_found("Each  PROCESS is holding a resource!", NOTES)   # case / spacing
    assert not generate.evidence_found("quantum computers break deadlocks instantly", NOTES)
    assert not generate.evidence_found("short", NOTES)


def test_generation_drops_malformed_and_rejects_ungrounded():
    service.create_subject("CS501", "OS")
    service.add_notes("CS501", [("os.pdf", NOTES)])
    stats = service.generate_questions("CS501", FakeLLM(bad_evidence=True))
    assert stats["draft"] == 0 and stats["auto_rejected"] == 2 * stats["topics"]  # broken question dropped
    assert all(q["status_reason"] == "evidence quote not found in the notes"
               for q in service.list_questions("CS501", "auto_rejected"))


# --- scheduler (pure) ------------------------------------------------------------------------

def test_coverage_pace_and_missed_days():
    start, exam = date(2026, 1, 1), date(2026, 4, 1)
    plan = scheduler.SubjectPlan(1, exam, start, list(range(60)), set())
    assert scheduler.topics_due_today(plan, start)[0] == 1                      # 60 topics, ~76 days
    late = date(2026, 3, 10)                                                    # nothing learned yet
    assert scheduler.topics_due_today(plan, late)[0] == scheduler.MAX_NEW_PER_DAY
    assert scheduler.is_behind(plan, late)
    assert scheduler.topics_due_today(plan, date(2026, 4, 2))[0] == 0           # exam passed


def test_subject_choice_prefers_most_behind():
    today = date(2026, 2, 1)
    relaxed = scheduler.SubjectPlan(1, date(2026, 5, 1), date(2026, 1, 1), list(range(10)), set())
    urgent = scheduler.SubjectPlan(2, date(2026, 3, 1), date(2026, 1, 1), list(range(100, 130)), set())
    assert scheduler.pick_subject([relaxed, urgent], today).subject_id == 2


def test_leitner():
    today = date(2026, 1, 1)
    assert scheduler.leitner_update(0, True, today) == (1, today + timedelta(days=2))
    assert scheduler.leitner_update(3, False, today) == (0, today + timedelta(days=1))
    assert scheduler.leitner_update(5, True, today)[0] == 5                     # top box stays
    due = [scheduler.DueReview(1, today, 3), scheduler.DueReview(2, today - timedelta(days=2), 4),
           scheduler.DueReview(3, today, 0), scheduler.DueReview(4, today + timedelta(days=1), 0)]
    assert scheduler.select_reviews(due, today, 3) == [2, 3, 1]                 # overdue, then weakest


# --- full student flow -----------------------------------------------------------------------

def test_daily_session_flow():
    make_subject()
    student = service.register_student("Asha Rao", "07:30")
    day1 = date.today()
    service.enroll(student.code, "CS501", exam_date=day1 + timedelta(days=90), start_date=day1)

    s1 = service.today_session(student.code, day1)
    assert s1["card"]["title"] == "Deadlocks" and [q["kind"] for q in s1["questions"]] == ["new", "new"]
    assert "answer_index" not in s1["questions"][0]                               # answers not leaked
    assert service.today_session(student.code, day1)["questions"] == s1["questions"]  # fixed for the day

    wrong = service.submit_answer(student.code, s1["questions"][0]["id"], 2, day1)
    assert not wrong["correct"] and wrong["next_review"] == (day1 + timedelta(days=1)).isoformat()
    done = service.submit_answer(student.code, s1["questions"][1]["id"], 0, day1)
    assert done["correct"] and done["session_completed"]

    s2 = service.today_session(student.code, day1 + timedelta(days=1))
    assert s2["card"]["topic_id"] != s1["card"]["topic_id"]                       # next topic
    assert {"id": s1["questions"][0]["id"], "kind": "review"} in [{"id": q["id"], "kind": q["kind"]} for q in s2["questions"]]

    prog = service.progress(student.code, day1)
    assert prog["subjects"][0]["covered"] == 2 and prog["streak_days"] == 1 and prog["accuracy"] == 0.5


def test_unapproved_questions_are_never_shown():
    make_subject(approve=False)
    student = service.register_student("Ravi")
    service.enroll(student.code, "CS501", exam_date=date.today() + timedelta(days=60))
    session = service.today_session(student.code)
    assert session["questions"] == [] and any("faculty approval" in n for n in session["notes"])


def test_reported_question_goes_back_to_review():
    make_subject()
    qid = service.list_questions("CS501", "approved")[0]["id"]
    service.report_question(qid)
    q = next(q for q in service.list_questions("CS501") if q["id"] == qid)
    assert q["status"] == "draft" and q["reports"] == 1


# --- reminders -------------------------------------------------------------------------------

def test_reminders_sent_once_per_day_after_chosen_time():
    from datetime import datetime

    make_subject()
    student = service.register_student("Asha Rao", "07:30")
    service.enroll(student.code, "CS501", exam_date=date.today() + timedelta(days=60))
    assert "Linked" in notify.handle_message("555", f"/start {student.code}")
    sent = []
    sender = lambda chat, text: sent.append((chat, text))  # noqa: E731
    today = date.today()
    assert notify.run_due(datetime.combine(today, datetime.min.time()).replace(hour=7), sender) == 0  # too early
    assert notify.run_due(datetime.combine(today, datetime.min.time()).replace(hour=8), sender) == 1
    assert notify.run_due(datetime.combine(today, datetime.min.time()).replace(hour=9), sender) == 0  # once a day
    assert sent[0][0] == "555" and "Hi Asha" in sent[0][1] and "Operating Systems" in sent[0][1]
    assert "Deadlocks" in notify.handle_message("555", "/today")


# --- API -------------------------------------------------------------------------------------

def test_api_student_flow_and_admin_key(monkeypatch):
    from daily10 import main

    make_subject()
    client = TestClient(main.app)
    code = client.post("/study/students", json={"name": "Asha", "notify_time": "07:30"}).json()["code"]
    assert client.post(f"/study/students/{code}/enroll",
                       json={"subject_code": "CS501", "exam_date": str(date.today() + timedelta(days=60))}).status_code == 200
    today = client.get(f"/study/students/{code}/today").json()
    qid = today["questions"][0]["id"]
    r = client.post(f"/study/students/{code}/answers", json={"question_id": qid, "chosen_index": 0}).json()
    assert r["correct"] and r["evidence"]
    assert client.get("/study/students/NOPE/today").status_code == 404
    me = client.get(f"/study/students/{code}").json()
    assert me["notify_time"] == "07:30" and me["subjects"][0]["code"] == "CS501" and not me["telegram_linked"]
    assert client.patch(f"/study/students/{code}", json={"notify_time": "21:15"}).status_code == 200
    assert client.get(f"/study/students/{code}").json()["notify_time"] == "21:15"
    assert client.post("/study/students", json={"name": "X", "notify_time": "25:00"}).status_code == 422

    monkeypatch.setenv("STUDY_ADMIN_KEY", "secret")
    assert client.get("/study/subjects/CS501/questions").status_code == 401
    assert client.get("/study/subjects/CS501/questions", headers={"X-Admin-Key": "secret"}).status_code == 200


def test_faculty_accounts_and_protected_endpoints(monkeypatch):
    from daily10 import main
    from daily10 import auth

    client = TestClient(main.app)
    monkeypatch.setenv("STUDY_ADMIN_KEY", "uni-invite")
    body = {"name": "Dr. Rao", "email": "Rao@UVCE.edu", "password": "longpassword1", "department": "CSE"}

    assert client.post("/study/faculty/register", json=body).status_code == 403                       # no invite
    assert client.post("/study/faculty/register", json=body | {"invite_code": "nope"}).status_code == 403
    r = client.post("/study/faculty/register", json=body | {"invite_code": "uni-invite"})
    assert r.status_code == 200 and r.json()["faculty"]["email"] == "rao@uvce.edu"
    assert client.post("/study/faculty/register", json=body | {"invite_code": "uni-invite"}).status_code == 409

    assert client.post("/study/faculty/login", json={"email": "rao@uvce.edu", "password": "wrong-pass"}).status_code == 401
    token = client.post("/study/faculty/login", json={"email": "RAO@uvce.edu", "password": "longpassword1"}).json()["token"]
    bearer = {"Authorization": f"Bearer {token}"}
    assert client.get("/study/faculty/me", headers=bearer).json()["name"] == "Dr. Rao"

    # Faculty endpoints: open to a valid token or the key, closed otherwise.
    assert client.post("/study/subjects", json={"code": "CS502", "name": "DBMS"}).status_code == 401
    assert client.post("/study/subjects", json={"code": "CS502", "name": "DBMS"}, headers=bearer).status_code == 200
    assert client.get("/study/subjects/CS502/questions", headers={"Authorization": "Bearer forged"}).status_code == 401
    client.post("/study/faculty/logout", headers=bearer)
    assert client.get("/study/subjects/CS502/questions", headers=bearer).status_code == 401           # logged out

    stored = auth.hash_password("longpassword1")
    assert stored.startswith("scrypt$") and "longpassword1" not in stored
    assert auth.verify_password("longpassword1", stored) and not auth.verify_password("other", stored)


# --- question quality ----------------------------------------------------------------------

def test_automatic_quality_issues():
    from daily10.quality import automatic_issues

    base = {"id": 2, "notes": NOTES, "prompt": "Which is a necessary condition for deadlock?",
            "options": ["Circular wait", "Paging", "Caching", "Hashing"], "answer_index": 0,
            "evidence": "each process is holding a resource"}
    assert automatic_issues(base, []) == []
    assert "options not 4 distinct" in automatic_issues(base | {"options": ["A", "A", "B", "C"]}, [])
    assert "evidence not in notes" in automatic_issues(base | {"evidence": "quantum deadlocks vanish instantly"}, [])
    assert "all/none-of-the-above option" in automatic_issues(base | {"options": ["X", "Y", "Z", "All of the above"]}, [])
    dup = base | {"id": 1}
    assert any("near-duplicate" in i for i in automatic_issues(base, [dup]))


def test_flag_reasons():
    from daily10.quality import flag_reason, judge_correct

    q = {"answer_index": 1}
    ok = {"chosen_index": 1, "another_option_also_correct": False, "answerable_from_notes": True, "clear": True}
    assert flag_reason(q, ok) is None and judge_correct(q, ok)
    assert "outside knowledge" in flag_reason(q, ok | {"answerable_from_notes": False})
    assert "another option" in flag_reason(q, ok | {"another_option_also_correct": True})
    assert "option C" in flag_reason(q, ok | {"chosen_index": 2})
    assert judge_correct(q, {"error": "x"}) is None


def test_check_questions_flags_drafts_and_sorts_them_first():
    make_subject(approve=False)

    class Judge:  # disagrees on every second question
        n = 0

        def invoke(self, prompt):
            Judge.n += 1

            class R:
                content = json.dumps({"chosen_index": 0 if Judge.n % 2 else 2, "another_option_also_correct": False,
                                      "answerable_from_notes": True, "clear": True, "note": ""})
            return R()

    stats = service.check_questions("CS501", Judge())
    assert stats["checked"] == stats["passed"] + stats["flagged"] and stats["flagged"] > 0
    drafts = service.list_questions("CS501", "draft")
    assert drafts[0]["status_reason"].startswith("AI check flagged")          # flagged first
    assert service.check_questions("CS501", Judge())["checked"] == 0           # not re-checked
