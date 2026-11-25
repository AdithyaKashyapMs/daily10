"""
Read-only views for faculty: a subject at a glance, one question in depth, and how the class
is doing (coverage, who is behind or inactive, hardest topics and questions).

Students appear by name only: no email addresses or internal ids.
"""

from datetime import date

from sqlalchemy import func, select

from daily10 import config, db, quality, scheduler
from daily10.db import Enrollment, PastQuestion, Question, Review, Student, Topic, TopicProgress
from daily10.service import NotFound, _question_view, get_subject, topic_overview

INACTIVE_DAYS = 7
MIN_ATTEMPTS = 3   # before a question's accuracy counts as "hard"


def _is_flagged(q: dict) -> bool:
    return bool(q.get("reports")) or q.get("status_reason", "").startswith(quality.FLAGGED)


def subject_overview(subject_code: str) -> dict:
    subject = get_subject(subject_code)
    topics = topic_overview(subject_code)
    with db.session() as s:
        by_status = dict(s.execute(select(Question.status, func.count()).join(Topic)
                                   .where(Topic.subject_id == subject.id).group_by(Question.status)).all())
        flagged = s.scalar(select(func.count()).select_from(Question).join(Topic).where(
            Topic.subject_id == subject.id, Question.status == "draft",
            (Question.reports > 0) | Question.status_reason.startswith(quality.FLAGGED)))
        unchecked = s.scalar(select(func.count()).select_from(Question).join(Topic).where(
            Topic.subject_id == subject.id, Question.status == "draft",
            ~Question.status_reason.startswith(quality.FLAGGED), ~Question.status_reason.startswith(quality.PASSED)))
        papers = s.scalar(select(func.count()).select_from(PastQuestion).where(PastQuestion.subject_id == subject.id))
        enrolled = s.execute(select(func.count(), func.min(Enrollment.exam_date))
                             .where(Enrollment.subject_id == subject.id)).one()
    return {
        "code": subject.code, "name": subject.name, "department": subject.department, "semester": subject.semester,
        "topics": len(topics), "topics_generated": sum(1 for t in topics if t["title"] != t["source"]),
        "questions_by_status": by_status,
        "review_queue": {"drafts": by_status.get("draft", 0), "flagged_or_reported": flagged, "not_ai_checked": unchecked,
                         "simple_explanations": sum(1 for t in topics if t["simple_status"] == "draft")},
        "past_paper_questions": papers, "students_enrolled": enrolled[0],
        "earliest_exam": enrolled[1].isoformat() if enrolled[1] else None,
        "topic_list": topics,
    }


def question_detail(question_id: int) -> dict:
    with db.session() as s:
        q = s.get(Question, question_id)
        if q is None:
            raise NotFound(f"No question {question_id}")
        topic = q.topic
        view = _question_view(q, topic, reveal=True)
        same = [{"id": x.id, "prompt": x.prompt} for x in topic.questions]
        attempts, correct, students = s.execute(
            select(func.coalesce(func.sum(Review.attempts), 0), func.coalesce(func.sum(Review.correct), 0),
                   func.count(Review.id)).where(Review.question_id == q.id)).one()
        view["automatic_issues"] = quality.automatic_issues({**view, "notes": topic.text}, same)
        view["subject"] = topic.subject.code
        view["student_results"] = {"students": students, "attempts": attempts,
                                   "accuracy": round(correct / attempts, 3) if attempts else None}
        return view


def class_insights(subject_code: str, today: date | None = None) -> dict:
    today = today or config.local_today()
    subject = get_subject(subject_code)
    with db.session() as s:
        topics = s.scalars(select(Topic).where(Topic.subject_id == subject.id).order_by(Topic.position)).all()
        topic_ids = [t.id for t in topics]
        rows = s.execute(select(Enrollment, Student).join(Student).where(Enrollment.subject_id == subject.id)).all()

        learned_by: dict[int, set[int]] = {}
        for student_id, topic_id in s.execute(select(TopicProgress.student_id, TopicProgress.topic_id)
                                              .where(TopicProgress.topic_id.in_(topic_ids or [-1]))):
            learned_by.setdefault(student_id, set()).add(topic_id)

        review_rows = s.execute(select(Review, Question.topic_id).join(Question)
                                .where(Question.topic_id.in_(topic_ids or [-1]))).all()

        students = []
        for e, st in rows:
            learned = learned_by.get(st.id, set())
            mine = [r for r, _ in review_rows if r.student_id == st.id]
            attempts, correct = sum(r.attempts for r in mine), sum(r.correct for r in mine)
            last = max((r.last_answered_on for r in mine if r.last_answered_on), default=None)
            plan = scheduler.SubjectPlan(subject.id, e.exam_date, e.start_date, topic_ids, learned)
            students.append({
                "name": st.name, "coverage": round(len(learned) / len(topic_ids), 3) if topic_ids else 0.0,
                "topics_left": len(topic_ids) - len(learned), "accuracy": round(correct / attempts, 3) if attempts else None,
                "answers": attempts, "last_active": last.isoformat() if last else None,
                "behind_schedule": scheduler.is_behind(plan, today),
                "inactive": last is None or (today - last).days >= INACTIVE_DAYS,
                "exam_date": e.exam_date.isoformat(),
            })

        per_topic = {t.id: {"topic_id": t.id, "title": t.title or t.source, "exam_weight": t.exam_weight,
                            "students_learned": 0, "attempts": 0, "correct": 0} for t in topics}
        for learned in learned_by.values():
            for tid in learned:
                per_topic[tid]["students_learned"] += 1
        per_q: dict[int, list[int]] = {}
        for r, tid in review_rows:
            per_topic[tid]["attempts"] += r.attempts
            per_topic[tid]["correct"] += r.correct
            per_q.setdefault(r.question_id, [0, 0])
            per_q[r.question_id][0] += r.attempts
            per_q[r.question_id][1] += r.correct
        topic_stats = []
        for t in per_topic.values():
            acc = round(t["correct"] / t["attempts"], 3) if t["attempts"] else None
            topic_stats.append({k: v for k, v in t.items() if k != "correct"} | {"accuracy": acc})

        hard_ids = sorted((qid for qid, (a, _) in per_q.items() if a >= MIN_ATTEMPTS),
                          key=lambda qid: per_q[qid][1] / per_q[qid][0])[:5]
        hardest = []
        for qid in hard_ids:
            q = s.get(Question, qid)
            hardest.append({"id": qid, "prompt": q.prompt, "topic_id": q.topic_id, "status": q.status,
                            "attempts": per_q[qid][0], "accuracy": round(per_q[qid][1] / per_q[qid][0], 3)})
        reported = [{"id": q.id, "prompt": q.prompt, "reports": q.reports, "status": q.status}
                    for q in s.scalars(select(Question).where(Question.topic_id.in_(topic_ids or [-1]),
                                                              Question.reports > 0).order_by(Question.reports.desc()))]

    answered = [st for st in students if st["accuracy"] is not None]
    weak = sorted((t for t in topic_stats if t["accuracy"] is not None and t["attempts"] >= MIN_ATTEMPTS),
                  key=lambda t: t["accuracy"])[:5]
    return {
        "subject": subject.code, "as_of": today.isoformat(),
        "summary": {
            "students": len(students),
            "average_coverage": round(sum(st["coverage"] for st in students) / len(students), 3) if students else None,
            "average_accuracy": round(sum(st["accuracy"] for st in answered) / len(answered), 3) if answered else None,
            "behind_schedule": sum(st["behind_schedule"] for st in students),
            f"inactive_{INACTIVE_DAYS}_days": sum(st["inactive"] for st in students),
        },
        "weakest_topics": weak,
        "hardest_questions": hardest,
        "reported_questions": reported,
        "students": sorted(students, key=lambda st: (not st["behind_schedule"], st["coverage"])),
        "topics": topic_stats,
    }


def filter_questions(questions: list[dict], flagged_only: bool = False, topic_id: int | None = None) -> list[dict]:
    return [q for q in questions
            if (not flagged_only or _is_flagged(q)) and (topic_id is None or q["topic_id"] == topic_id)]
