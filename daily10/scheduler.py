"""
What a student studies today. Pure functions: no database, easy to test.

Coverage plan (new topics). Each subject's topics should all be seen before a revision
window at the end (REVISION_DAYS before the exam, or less for short courses). Every day:

    topics needed today = ceil(topics left / days left before the revision window)

capped at MAX_NEW_PER_DAY so a session stays ~10 minutes. Because this is recomputed daily,
a missed day just spreads the backlog over the remaining days instead of doubling tomorrow;
if even the cap can't catch up, the session says the student is behind.
One subject gets the new topic each day: the one most behind (highest topics-left per
day-left), ties broken by the nearest exam.

Spaced repetition (reviews). Leitner boxes: a correct answer moves a question up a box and
schedules it further out (1, 2, 4, 8, 16, 32 days); a wrong answer sends it back to box 0,
due tomorrow. Each day shows the questions that are due, most overdue and weakest first.
"""

import math
from dataclasses import dataclass
from datetime import date, timedelta

REVISION_DAYS = 14
MAX_NEW_PER_DAY = 2
NEW_QUESTIONS = 3
REVIEWS_WITH_NEW_TOPIC = 2
REVIEWS_REVISION_ONLY = 5
LEITNER_DAYS = [1, 2, 4, 8, 16, 32]


@dataclass
class SubjectPlan:
    subject_id: int
    exam_date: date
    start_date: date
    topic_ids: list[int]          # syllabus order
    learned: set[int]


@dataclass
class DueReview:
    question_id: int
    due_on: date
    box: int


def revision_start(start: date, exam: date) -> date:
    """New material should be finished by this day; the rest is revision."""
    span = max((exam - start).days, 1)
    window = min(REVISION_DAYS, span // 5)  # short courses keep most days for new material
    return exam - timedelta(days=window)


def topics_due_today(plan: SubjectPlan, today: date) -> tuple[int, int]:
    """(topics to learn today, topics left). 0 if done or the exam has passed."""
    left = [t for t in plan.topic_ids if t not in plan.learned]
    if not left or today > plan.exam_date:
        return 0, len(left)
    days_left = max((revision_start(plan.start_date, plan.exam_date) - today).days + 1, 1)
    return min(math.ceil(len(left) / days_left), MAX_NEW_PER_DAY), len(left)


def pick_subject(plans: list[SubjectPlan], today: date) -> SubjectPlan | None:
    """The subject that gets today's new topic: most behind, then nearest exam."""
    def urgency(p: SubjectPlan) -> tuple[float, int]:
        needed, left = topics_due_today(p, today)
        if needed == 0:
            return (-1.0, 0)
        days_left = max((revision_start(p.start_date, p.exam_date) - today).days + 1, 1)
        return (left / days_left, -(p.exam_date - today).days)

    candidates = [p for p in plans if topics_due_today(p, today)[0] > 0]
    return max(candidates, key=urgency) if candidates else None


def next_topic(plan: SubjectPlan) -> int | None:
    return next((t for t in plan.topic_ids if t not in plan.learned), None)


def is_behind(plan: SubjectPlan, today: date) -> bool:
    """True if even MAX_NEW_PER_DAY a day won't finish the topics before revision starts."""
    left = len([t for t in plan.topic_ids if t not in plan.learned])
    days_left = max((revision_start(plan.start_date, plan.exam_date) - today).days + 1, 1)
    return left > days_left * MAX_NEW_PER_DAY


def select_reviews(due: list[DueReview], today: date, k: int) -> list[int]:
    """Up to k due question ids: most overdue first, then lowest box (weakest)."""
    ready = [r for r in due if r.due_on <= today]
    ready.sort(key=lambda r: (r.due_on, r.box, r.question_id))
    return [r.question_id for r in ready[:k]]


def leitner_update(box: int, correct: bool, today: date) -> tuple[int, date]:
    """New (box, due date) after an answer."""
    new_box = min(box + 1, len(LEITNER_DAYS) - 1) if correct else 0
    return new_box, today + timedelta(days=LEITNER_DAYS[new_box])
