"""
Daily 10 operations, used by the API, the UI, the CLI and the notifier.
"""

import secrets
from datetime import date, timedelta

import logging
from sqlalchemy import func, select

from daily10 import config, content, db, generate, scheduler
from daily10.db import (
    DailySession,
    Enrollment,
    PastQuestion,
    Question,
    Review,
    Student,
    Subject,
    Topic,
    TopicProgress,
)


log = logging.getLogger(__name__)


class NotFound(LookupError):
    pass


# --- Faculty / admin: content ------------------------------------------------------------

def create_subject(code: str, name: str, department: str = "", semester: int = 0) -> Subject:
    with db.session() as s:
        subject = Subject(code=code.strip().upper(), name=name.strip(), department=department, semester=semester)
        s.add(subject)
        s.commit()
        return subject


def get_subject(code: str) -> Subject:
    with db.session() as s:
        subject = s.scalar(select(Subject).where(Subject.code == code.strip().upper()))
        if not subject:
            raise NotFound(f"No subject {code}")
        return subject


def add_notes(subject_code: str, texts: list[tuple[str, str]]) -> int:
    """Append topics from (source name, text) pairs, in order. Returns topics added."""
    subject = get_subject(subject_code)
    with db.session() as s:
        position = s.scalar(select(func.coalesce(func.max(Topic.position), 0)).where(Topic.subject_id == subject.id))
        added = 0
        for source, text in texts:
            for t in content.split_into_topics(text, source):
                position += 1
                s.add(Topic(subject_id=subject.id, position=position, source=t["source"], text=t["text"]))
                added += 1
        s.commit()
    log.info(f"Added {added} topics to {subject.code}")
    return added


def add_past_paper(subject_code: str, text: str, year: int | None = None) -> int:
    """Split a past exam paper into questions, match each to a topic, update exam weights."""
    subject = get_subject(subject_code)
    with db.session() as s:
        topics = s.scalars(select(Topic).where(Topic.subject_id == subject.id).order_by(Topic.position)).all()
        if not topics:
            raise ValueError("Add the notes before the past papers (questions are matched to topics).")
        questions = content.split_past_paper(text)
        matches = content.match_to_topics([q["text"] for q in questions], [{"text": t.text} for t in topics])
        for q, idx in zip(questions, matches):
            topic = topics[idx] if idx is not None else None
            s.add(PastQuestion(subject_id=subject.id, topic_id=topic.id if topic else None,
                               text=q["text"], year=year, marks=q["marks"]))
            if topic:
                topic.exam_weight += 1
        s.commit()
        return len(questions)


def _store_simple(topic: Topic, layer: "generate.SimpleLayer") -> bool:
    """Save a topic's simple layer as a draft for faculty review. False if the model gave nothing usable."""
    if not layer.has_content():
        return False
    topic.simple_explanation, topic.analogy = layer.simple_explanation.strip(), layer.analogy.strip()
    topic.glossary = [g.model_dump() for g in layer.glossary]
    topic.simple_status = "draft"
    return True


def generate_questions(subject_code: str, llm, only_missing: bool = True, limit: int | None = None) -> dict:
    """
    Run the LLM over each topic: title, summary, key points, the simple layer and grounded
    questions (all as drafts). Topics generated before the simple layer existed get just that
    layer, and the same call tags their existing questions warmup / core / exam.
    `limit` counts LLM calls (topics), to stay inside free-tier quotas.
    """
    subject = get_subject(subject_code)
    stats = {"topics": 0, "draft": 0, "auto_rejected": 0, "failed_topics": 0, "simple_explanations": 0,
             "levels_tagged": 0}
    with db.session() as s:
        topics = s.scalars(select(Topic).where(Topic.subject_id == subject.id).order_by(Topic.position)).all()
        for topic in topics:
            backfill = bool(topic.summary) and not topic.simple_status
            if only_missing and topic.summary and not backfill:
                continue
            if limit is not None and stats["topics"] >= limit:
                break
            try:
                if only_missing and backfill:
                    existing = [(q.id, q.prompt) for q in topic.questions if q.status in ("draft", "approved")]
                    layer, levels = generate.generate_simple(topic.text, llm, existing)
                    stats["simple_explanations"] += _store_simple(topic, layer)
                    for q in topic.questions:
                        if q.id in levels:
                            q.level = levels[q.id]
                    stats["levels_tagged"] += len(levels)
                    stats["topics"] += 1
                    s.commit()
                    continue
                pack = generate.generate_pack(topic.text, llm)
            except Exception as e:
                log.error(f"Generation failed for topic {topic.id}: {e}")
                stats["failed_topics"] += 1
                continue
            topic.title, topic.summary, topic.key_points = pack.title, pack.summary, pack.key_points
            stats["simple_explanations"] += _store_simple(topic, pack)
            for q in pack.questions:
                issue = generate.grounding_issue(q, topic.text)
                s.add(Question(
                    topic_id=topic.id, prompt=q.question, options=q.options, answer_index=q.answer_index,
                    explanation=q.explanation, evidence=q.evidence, level=q.level,
                    status="auto_rejected" if issue else "draft", status_reason=issue or "",
                ))
                stats["auto_rejected" if issue else "draft"] += 1
            stats["topics"] += 1
            s.commit()
    return stats


def list_questions(subject_code: str, status: str | None = None) -> list[dict]:
    subject = get_subject(subject_code)
    with db.session() as s:
        stmt = select(Question, Topic).join(Topic).where(Topic.subject_id == subject.id)
        if status:
            stmt = stmt.where(Question.status == status)
        rows = s.execute(stmt.order_by(Topic.position, Question.id)).all()
        views = [_question_view(q, t, reveal=True) for q, t in rows]
        # Reported or AI-flagged questions first: they need a closer look.
        return sorted(views, key=lambda v: not (v["reports"] or v["status_reason"].startswith("AI check flagged")))


def set_question_status(question_id: int, status: str, reason: str = "") -> None:
    if status not in ("approved", "rejected", "draft"):
        raise ValueError("status must be approved, rejected or draft")
    with db.session() as s:
        q = s.get(Question, question_id)
        if not q:
            raise NotFound(f"No question {question_id}")
        q.status, q.status_reason = status, reason
        s.commit()


def set_question_level(question_id: int, level: str) -> dict:
    """Re-tag a question warmup / core / exam. Its content doesn't change, so it keeps its status."""
    if level not in generate.LEVELS:
        raise ValueError(f"level must be one of {', '.join(generate.LEVELS)}")
    with db.session() as s:
        q = s.get(Question, question_id)
        if not q:
            raise NotFound(f"No question {question_id}")
        q.level = level
        s.commit()
        return _question_view(q, q.topic, reveal=True)


def _explanation_view(t: Topic) -> dict:
    return {"topic_id": t.id, "position": t.position, "title": t.title or t.source, "summary": t.summary,
            "simple_explanation": t.simple_explanation, "analogy": t.analogy, "glossary": t.glossary or [],
            "status": t.simple_status}


def list_explanations(subject_code: str, status: str | None = None) -> list[dict]:
    """Topics' simple layers for faculty review (topics without one are left out)."""
    subject = get_subject(subject_code)
    with db.session() as s:
        stmt = select(Topic).where(Topic.subject_id == subject.id, Topic.simple_status != "")
        if status:
            stmt = stmt.where(Topic.simple_status == status)
        return [_explanation_view(t) for t in s.scalars(stmt.order_by(Topic.position))]


def review_explanation(topic_id: int, status: str, changes: dict | None = None) -> dict:
    """
    Approve or reject a topic's simple layer, optionally fixing the wording first. Glossary terms
    must still appear in the topic's notes; students see the layer only once it is approved.
    """
    if status not in ("approved", "rejected", "draft"):
        raise ValueError("status must be approved, rejected or draft")
    changes = {k: v for k, v in (changes or {}).items() if v is not None}
    unknown = set(changes) - {"simple_explanation", "analogy", "glossary"}
    if unknown:
        raise ValueError(f"Can't edit {sorted(unknown)}")
    with db.session() as s:
        t = s.get(Topic, topic_id)
        if not t:
            raise NotFound(f"No topic {topic_id}")
        if "simple_explanation" in changes:
            t.simple_explanation = changes["simple_explanation"].strip()
        if "analogy" in changes:
            t.analogy = changes["analogy"].strip()
        if "glossary" in changes:
            terms = [generate.GlossaryTerm.model_validate(g) for g in changes["glossary"]]
            t.glossary = [g.model_dump() for g in generate.grounded_glossary(terms, t.text)]
        if status == "approved" and not (t.simple_explanation or t.glossary):
            raise ValueError("Nothing to approve: this topic has no simple explanation yet.")
        t.simple_status = status
        s.commit()
        return _explanation_view(t)


def edit_question(question_id: int, changes: dict, editor: str = "faculty") -> dict:
    """
    Change a question's wording, options, answer or evidence. The result goes through the same
    checks as generated questions (4 distinct options, evidence quoted from the topic's notes)
    and goes back to draft, so it is approved (and AI-checked) again before students see it.
    """
    allowed = {"prompt", "options", "answer_index", "explanation", "evidence"}
    unknown = set(changes) - allowed
    if unknown:
        raise ValueError(f"Can't edit {sorted(unknown)}; editable fields: {sorted(allowed)}")
    with db.session() as s:
        q = s.get(Question, question_id)
        if not q:
            raise NotFound(f"No question {question_id}")
        merged = {"prompt": q.prompt, "options": q.options, "answer_index": q.answer_index,
                  "explanation": q.explanation, "evidence": q.evidence} | {k: v for k, v in changes.items() if v is not None}
        checked = generate.GeneratedQuestion(question=merged["prompt"], options=merged["options"],
                                             answer_index=merged["answer_index"], explanation=merged["explanation"],
                                             evidence=merged["evidence"])
        issue = generate.grounding_issue(checked, q.topic.text)
        if issue:
            raise ValueError(f"{issue}: quote the evidence word for word from topic {q.topic_id}'s notes")
        q.prompt, q.options, q.answer_index = checked.question, checked.options, checked.answer_index
        q.explanation, q.evidence = checked.explanation, checked.evidence
        q.status, q.status_reason = "draft", f"edited by {editor}; needs approval"
        s.commit()
        return _question_view(q, q.topic, reveal=True)


def add_question(topic_id: int, q: "generate.GeneratedQuestion", reason: str) -> dict:
    """Save a question written on request (not by bulk generation) after the usual checks."""
    from daily10 import quality

    with db.session() as s:
        topic = s.get(Topic, topic_id)
        if not topic:
            raise NotFound(f"No topic {topic_id}")
        same_topic = [{"id": x.id, "prompt": x.prompt} for x in topic.questions]
        issues = quality.automatic_issues(
            {"id": 10**9, "prompt": q.question, "options": q.options, "answer_index": q.answer_index,
             "evidence": q.evidence, "notes": topic.text}, same_topic)
        row = Question(topic_id=topic.id, prompt=q.question, options=q.options, answer_index=q.answer_index,
                       explanation=q.explanation, evidence=q.evidence, level=q.level,
                       status="auto_rejected" if issues else "draft",
                       status_reason="; ".join(issues) if issues else reason)
        s.add(row)
        s.commit()
        return _question_view(row, topic, reveal=True)


def report_question(question_id: int, reason: str = "") -> None:
    """A student says the question is wrong: count it and send it back for faculty review."""
    with db.session() as s:
        q = s.get(Question, question_id)
        if not q:
            raise NotFound(f"No question {question_id}")
        q.reports += 1
        note = f": {reason.strip()[:200]}" if reason.strip() else ""
        q.status, q.status_reason = "draft", f"reported by students ({q.reports}){note}"
        s.commit()


def topic_overview(subject_code: str) -> list[dict]:
    """Topics with exam weight and question counts: the "most asked topics" view."""
    subject = get_subject(subject_code)
    with db.session() as s:
        topics = s.scalars(select(Topic).where(Topic.subject_id == subject.id).order_by(Topic.position)).all()
        out = []
        for t in topics:
            counts = dict(s.execute(select(Question.status, func.count()).where(Question.topic_id == t.id)
                                    .group_by(Question.status)).all())
            out.append({"id": t.id, "position": t.position, "title": t.title or t.source, "source": t.source,
                        "exam_weight": t.exam_weight, "questions": counts, "simple_status": t.simple_status})
        return out


# --- Students ------------------------------------------------------------------------------

def register_student(name: str, notify_time: str = "19:00", email: str | None = None) -> Student:
    with db.session() as s:
        student = Student(code=secrets.token_hex(3).upper(), name=name.strip(), notify_time=notify_time, email=email)
        s.add(student)
        s.commit()
        return student


def get_student(code: str) -> Student:
    with db.session() as s:
        student = s.scalar(select(Student).where(Student.code == code.strip().upper()))
        if not student:
            raise NotFound(f"No student {code}")
        return student


def enroll(student_code: str, subject_code: str, exam_date: date, start_date: date | None = None) -> None:
    student, subject = get_student(student_code), get_subject(subject_code)
    with db.session() as s:
        existing = s.scalar(select(Enrollment).where(Enrollment.student_id == student.id,
                                                     Enrollment.subject_id == subject.id))
        if existing:
            existing.exam_date = exam_date
        else:
            s.add(Enrollment(student_id=student.id, subject_id=subject.id,
                             start_date=start_date or config.local_today(), exam_date=exam_date))
        s.commit()


def set_preferences(student_code: str, notify_time: str | None = None, telegram_chat_id: str | None = None,
                    name: str | None = None) -> None:
    student = get_student(student_code)
    with db.session() as s:
        st = s.get(Student, student.id)
        if name:
            st.name = name.strip()[:120]
        if notify_time:
            st.notify_time = notify_time
        if telegram_chat_id is not None:
            st.telegram_chat_id = telegram_chat_id or None  # "" unlinks
        s.commit()


# --- The daily session ---------------------------------------------------------------------

def _question_view(q: Question, topic: Topic, reveal: bool = False) -> dict:
    view = {"id": q.id, "topic": topic.title or topic.source, "prompt": q.prompt, "options": q.options,
            "level": q.level or "core"}
    if reveal:
        view |= {"topic_id": topic.id, "answer_index": q.answer_index, "explanation": q.explanation, "evidence": q.evidence,
                 "status": q.status, "status_reason": q.status_reason, "reports": q.reports}
    return view


def _subject_plans(s, student: Student) -> list[scheduler.SubjectPlan]:
    learned = set(s.scalars(select(TopicProgress.topic_id).where(TopicProgress.student_id == student.id)))
    plans = []
    for e in s.scalars(select(Enrollment).where(Enrollment.student_id == student.id)):
        topic_ids = list(s.scalars(select(Topic.id).where(Topic.subject_id == e.subject_id).order_by(Topic.position)))
        plans.append(scheduler.SubjectPlan(e.subject_id, e.exam_date, e.start_date, topic_ids, learned))
    return plans


def _simple_layer(topic: Topic) -> dict | None:
    """What students see of the "explain simply" layer: only once faculty approved it."""
    if topic.simple_status != "approved":
        return None
    return {"explanation": topic.simple_explanation, "analogy": topic.analogy, "glossary": topic.glossary or []}


def _terms_in(glossary: list[dict], text: str) -> list[dict]:
    """Glossary entries whose term appears in `text` (a question, its options and explanation)."""
    words = " " + " ".join(generate._words(text)) + " "
    return [g for g in glossary if f" {' '.join(generate._words(g['term']))} " in words]


def _band(s, student_id: int, subject_id: int) -> str:
    """The student's learner band in one subject, from their answers so far."""
    attempts, correct = s.execute(
        select(func.coalesce(func.sum(Review.attempts), 0), func.coalesce(func.sum(Review.correct), 0))
        .select_from(Review).join(Question).join(Topic)
        .where(Review.student_id == student_id, Topic.subject_id == subject_id)).one()
    return scheduler.learner_band(int(attempts), int(correct))


def _build_plan(s, student: Student, today: date) -> dict:
    plans = _subject_plans(s, student)
    chosen = scheduler.pick_subject(plans, today)
    plan: dict = {"day": today.isoformat(), "card": None, "questions": [], "past_question": None, "notes": []}

    if chosen:
        topic = s.get(Topic, scheduler.next_topic(chosen))
        subject = s.get(Subject, chosen.subject_id)
        band = _band(s, student.id, subject.id)
        plan["card"] = {"topic_id": topic.id, "subject": subject.name, "title": topic.title or topic.source,
                        "summary": topic.summary, "key_points": topic.key_points, "source": topic.source,
                        "exam_weight": topic.exam_weight, "start_simple": band == "struggling"}
        available = s.execute(select(Question.id, Question.level)
                              .where(Question.topic_id == topic.id, Question.status == "approved")).all()
        new_qs = scheduler.pick_new_questions([(qid, level or "core") for qid, level in available], band)
        plan["questions"] += [{"id": qid, "kind": "new"} for qid in new_qs]
        past = s.scalar(select(PastQuestion).where(PastQuestion.topic_id == topic.id)
                        .order_by(PastQuestion.year.desc().nulls_last(), PastQuestion.id))
        if past:
            plan["past_question"] = {"text": past.text, "year": past.year, "marks": past.marks}
        s.add(TopicProgress(student_id=student.id, topic_id=topic.id, learned_on=today))
        if scheduler.is_behind(chosen, today):
            plan["notes"].append(f"You're behind schedule in {subject.name}; a few extra sessions this week would help.")
        if not new_qs:
            plan["notes"].append("Questions for this topic are still waiting for faculty approval.")

    k = scheduler.REVIEWS_WITH_NEW_TOPIC if chosen else scheduler.REVIEWS_REVISION_ONLY
    due = [scheduler.DueReview(r.question_id, r.due_on, r.box)
           for r in s.scalars(select(Review).join(Question)
                              .where(Review.student_id == student.id, Review.due_on <= today,
                                     Question.status == "approved"))]
    plan["questions"] += [{"id": qid, "kind": "review"} for qid in scheduler.select_reviews(due, today, k)]
    if not chosen and not plan["questions"]:
        plan["notes"].append("Nothing due today. You're on track!")
    return plan


def today_session(student_code: str, today: date | None = None) -> dict:
    """Today's session for a student. Built on first open, then fixed for the day."""
    today = today or config.local_today()
    student = get_student(student_code)
    with db.session() as s:
        existing = s.scalar(select(DailySession).where(DailySession.student_id == student.id,
                                                       DailySession.day == today))
        if existing is None:
            existing = DailySession(student_id=student.id, day=today, plan=_build_plan(s, student, today))
            s.add(existing)
            s.commit()
        plan = dict(existing.plan)
        answered = set(s.scalars(select(Review.question_id).where(Review.student_id == student.id,
                                                                  Review.last_answered_on == today)))
        questions = []
        for item in plan["questions"]:
            q = s.get(Question, item["id"])
            if q is None:
                continue
            questions.append({**_question_view(q, q.topic), "kind": item["kind"], "answered": q.id in answered})
        if plan.get("card"):
            topic = s.get(Topic, plan["card"]["topic_id"])
            plan["card"] = {"start_simple": False, **plan["card"], "simple": _simple_layer(topic) if topic else None}
        return {**plan, "questions": questions, "completed": existing.completed, "student": student.name}


def submit_answer(student_code: str, question_id: int, chosen_index: int, today: date | None = None) -> dict:
    """Record an answer, update spaced repetition, and return the correct answer with its evidence."""
    today = today or config.local_today()
    student = get_student(student_code)
    with db.session() as s:
        q = s.get(Question, question_id)
        if q is None:
            raise NotFound(f"No question {question_id}")
        correct = chosen_index == q.answer_index
        review = s.scalar(select(Review).where(Review.student_id == student.id, Review.question_id == q.id))
        if review is None:
            review = Review(student_id=student.id, question_id=q.id, box=0, due_on=today, attempts=0, correct=0)
            s.add(review)
        review.box, review.due_on = scheduler.leitner_update(review.box, correct, today)
        review.attempts += 1
        review.correct += int(correct)
        review.last_answered_on = today

        session = s.scalar(select(DailySession).where(DailySession.student_id == student.id, DailySession.day == today))
        if session:
            planned = {item["id"] for item in session.plan["questions"]}
            s.flush()
            done = set(s.scalars(select(Review.question_id).where(Review.student_id == student.id,
                                                                  Review.last_answered_on == today)))
            session.completed = planned <= done
        help_ = None
        layer = None if correct else _simple_layer(q.topic)
        if layer:
            text = " ".join([q.prompt, *q.options, q.explanation])
            help_ = {"explanation": layer["explanation"], "analogy": layer["analogy"],
                     "glossary": _terms_in(layer["glossary"], text)}
        s.commit()
        return {"correct": correct, "answer_index": q.answer_index, "explanation": q.explanation,
                "evidence": q.evidence, "next_review": review.due_on.isoformat(),
                "session_completed": bool(session and session.completed), "simple": help_}


def progress(student_code: str, today: date | None = None) -> dict:
    """Coverage per subject, streak, and weakest topics."""
    today = today or config.local_today()
    student = get_student(student_code)
    with db.session() as s:
        learned = set(s.scalars(select(TopicProgress.topic_id).where(TopicProgress.student_id == student.id)))
        subjects = []
        for e in s.scalars(select(Enrollment).where(Enrollment.student_id == student.id)):
            topic_ids = list(s.scalars(select(Topic.id).where(Topic.subject_id == e.subject_id)))
            covered = len([t for t in topic_ids if t in learned])
            subjects.append({"subject": e.subject.name, "code": e.subject.code, "exam_date": e.exam_date.isoformat(),
                             "topics": len(topic_ids), "covered": covered,
                             "coverage": round(covered / len(topic_ids), 3) if topic_ids else 0.0,
                             "days_to_exam": (e.exam_date - today).days})
        # Streak: consecutive completed days ending today (or yesterday, if today isn't done yet).
        done_days = set(s.scalars(select(DailySession.day).where(DailySession.student_id == student.id,
                                                                 DailySession.completed.is_(True))))
        day = today if today in done_days else today - timedelta(days=1)
        streak = 0
        while day in done_days:
            streak += 1
            day -= timedelta(days=1)
        attempts, correct = s.execute(select(func.coalesce(func.sum(Review.attempts), 0),
                                             func.coalesce(func.sum(Review.correct), 0))
                                      .where(Review.student_id == student.id)).one()
        weak = s.execute(
            select(Topic.title, Topic.source, func.sum(Review.attempts - Review.correct).label("misses"))
            .select_from(Review).join(Question).join(Topic)
            .where(Review.student_id == student.id)
            .group_by(Topic.id).having(func.sum(Review.attempts - Review.correct) > 0)
            .order_by(func.sum(Review.attempts - Review.correct).desc()).limit(3)
        ).all()
        return {"student": student.name, "subjects": subjects, "streak_days": streak,
                "accuracy": round(correct / attempts, 3) if attempts else None, "answers": attempts,
                "weak_topics": [{"topic": t or src, "misses": m} for t, src, m in weak]}


def students_to_notify(now_hhmm: str, today: date) -> list[Student]:
    """Students with Telegram linked whose reminder time has passed today and who weren't reminded yet."""
    with db.session() as s:
        return list(s.scalars(select(Student).where(
            Student.telegram_chat_id.is_not(None),
            Student.notify_time <= now_hhmm,
            (Student.last_notified_on.is_(None)) | (Student.last_notified_on < today),
        )))


def mark_notified(student_id: int, today: date) -> None:
    with db.session() as s:
        st = s.get(Student, student_id)
        st.last_notified_on = today
        s.commit()


def preview_today(student_code: str, today: date | None = None) -> dict:
    """What today's session will cover, without building it (used for reminders)."""
    today = today or config.local_today()
    student = get_student(student_code)
    with db.session() as s:
        existing = s.scalar(select(DailySession).where(DailySession.student_id == student.id, DailySession.day == today))
        if existing:
            card = existing.plan.get("card") or {}
            return {"subject": card.get("subject"), "topic": card.get("title"), "completed": existing.completed,
                    "reviews": sum(q["kind"] == "review" for q in existing.plan["questions"])}
        chosen = scheduler.pick_subject(_subject_plans(s, student), today)
        topic = s.get(Topic, scheduler.next_topic(chosen)) if chosen else None
        due = s.scalar(select(func.count()).select_from(Review).where(Review.student_id == student.id,
                                                                      Review.due_on <= today))
        return {"subject": s.get(Subject, chosen.subject_id).name if chosen else None,
                "topic": (topic.title or topic.source) if topic else None, "completed": False, "reviews": due}


def student_by_chat(chat_id: str) -> Student | None:
    with db.session() as s:
        return s.scalar(select(Student).where(Student.telegram_chat_id == chat_id))


def list_subjects() -> list[dict]:
    with db.session() as s:
        rows = s.execute(select(Subject, func.count(Topic.id)).outerjoin(Topic).group_by(Subject.id)
                         .order_by(Subject.semester, Subject.code)).all()
        return [{"code": sub.code, "name": sub.name, "department": sub.department, "semester": sub.semester,
                 "topics": n} for sub, n in rows]


def student_profile(student_code: str) -> dict:
    student = get_student(student_code)
    with db.session() as s:
        enrolled = [{"code": e.subject.code, "name": e.subject.name, "exam_date": e.exam_date.isoformat()}
                    for e in s.scalars(select(Enrollment).where(Enrollment.student_id == student.id))]
    return {"name": student.name, "email": student.email, "notify_time": student.notify_time,
            "telegram_linked": bool(student.telegram_chat_id), "subjects": enrolled,
            "needs_profile": not (student.name or "").strip()}


def check_questions(subject_code: str, llm, recheck: bool = False) -> dict:
    """
    Run the independent AI check on draft questions. Failing ones stay drafts, marked
    "AI check flagged: <reason>" so faculty review them first; passing ones are marked passed.
    Faculty still approve every question: the check sets review priority, it doesn't approve.
    """
    from daily10 import quality

    subject = get_subject(subject_code)
    stats = {"checked": 0, "passed": 0, "flagged": 0, "errors": 0}
    with db.session() as s:
        rows = s.execute(select(Question, Topic).join(Topic)
                         .where(Topic.subject_id == subject.id, Question.status == "draft")).all()
        for q, topic in rows:
            if not recheck and q.status_reason.startswith((quality.PASSED, quality.FLAGGED)):
                continue
            item = {"id": q.id, "notes": topic.text, "prompt": q.prompt, "options": q.options, "answer_index": q.answer_index}
            verdict = quality.judge([item], llm)[q.id]
            stats["checked"] += 1
            if "error" in verdict:
                stats["errors"] += 1
                continue
            reason = quality.flag_reason(item, verdict)
            q.status_reason = f"{quality.FLAGGED}: {reason}" if reason else quality.PASSED
            stats["flagged" if reason else "passed"] += 1
            s.commit()
    return stats
