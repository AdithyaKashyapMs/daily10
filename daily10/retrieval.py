"""
Passage search over a subject's notes and past papers, for the MCP server and the RAG agent.

Each topic's notes are split into passages (same splitter as topics) with citation ids like
"T12#3" (topic 12, passage 3). Search is BM25 keyword search (CamelCase identifiers split and words stemmed, so
"autoscaling" finds HorizontalPodAutoscaler): no embedding model or vector
database to run, and exam-style queries are full of exact technical terms, which BM25 handles
well. Weak keyword matches are handled by the agent instead: it rephrases and searches again.

The index for a subject is built on first use and cached until its topics change.
Past-paper questions get ids like "P7".
"""

from sqlalchemy import case, func, select

from daily10 import db
from daily10.db import PastQuestion, Question, Topic
from daily10.service import NotFound, get_subject
from daily10.textproc import BM25Index, chunk_text, search_tokenize

_cache: dict[int, tuple[tuple, BM25Index]] = {}


def _signature(s, subject_id: int) -> tuple:
    # Topics are only ever appended, and titles are filled in by generation.
    return tuple(s.execute(
        select(func.count(Topic.id), func.max(Topic.id), func.sum(case((Topic.title != "", 1), else_=0)))
        .where(Topic.subject_id == subject_id)
    ).one())


def topic_passages(topic: Topic) -> list[dict]:
    title = topic.title or topic.source
    return [{"id": f"T{topic.id}#{i}", "topic_id": topic.id, "topic": title, "source": topic.source,
             "position": topic.position, "content": chunk}
            for i, chunk in enumerate(chunk_text(topic.text))]


def _index(subject_id: int) -> BM25Index:
    with db.session() as s:
        sig = _signature(s, subject_id)
        cached = _cache.get(subject_id)
        if cached and cached[0] == sig:
            return cached[1]
        topics = s.scalars(select(Topic).where(Topic.subject_id == subject_id).order_by(Topic.position)).all()
        passages = [p for t in topics for p in topic_passages(t)]
    # The topic title is indexed with each passage so "what is X" finds X's topic.
    index = BM25Index([{**p, "_text": p["content"], "content": f"{p['topic']}\n{p['content']}"} for p in passages],
                      tokenizer=search_tokenize)
    _cache[subject_id] = (sig, index)
    return index


def search_notes(subject_code: str, query: str, top_k: int = 5, topic_id: int | None = None) -> list[dict]:
    """Best-matching passages from the subject's notes, each with a citation id."""
    subject = get_subject(subject_code)
    index = _index(subject.id)
    hits = index.search(query, limit=len(index.docs) if topic_id else top_k)
    if topic_id is not None:
        hits = [h for h in hits if h["topic_id"] == topic_id]
    return [{"id": h["id"], "topic_id": h["topic_id"], "topic": h["topic"], "source": h["source"],
             "score": round(h["score"], 3), "content": h["_text"]} for h in hits[:top_k]]


def read_topic(topic_id: int) -> dict:
    """One topic in full: notes split into citable passages, generated summary, past questions."""
    with db.session() as s:
        t = s.get(Topic, topic_id)
        if t is None:
            raise NotFound(f"No topic {topic_id}")
        neighbours = dict(s.execute(select(Topic.position, Topic.id).where(
            Topic.subject_id == t.subject_id, Topic.position.in_([t.position - 1, t.position + 1]))).all())
        counts = dict(s.execute(select(Question.status, func.count()).where(Question.topic_id == t.id)
                                .group_by(Question.status)).all())
        past = s.scalars(select(PastQuestion).where(PastQuestion.topic_id == t.id)
                         .order_by(PastQuestion.year.desc().nulls_last())).all()
        return {
            "id": t.id, "subject": t.subject.code, "position": t.position, "title": t.title or t.source,
            "source": t.source, "summary": t.summary, "key_points": t.key_points, "exam_weight": t.exam_weight,
            "questions": counts,
            "past_questions": [{"id": f"P{p.id}", "text": p.text, "year": p.year, "marks": p.marks} for p in past],
            "previous_topic_id": neighbours.get(t.position - 1), "next_topic_id": neighbours.get(t.position + 1),
            "passages": [{"id": p["id"], "content": p["content"]} for p in topic_passages(t)],
        }


def search_past_papers(subject_code: str, query: str | None = None, top_k: int = 10) -> list[dict]:
    """Past exam questions matching the query (or all of them, newest first, without one)."""
    subject = get_subject(subject_code)
    with db.session() as s:
        rows = s.execute(select(PastQuestion, Topic).outerjoin(Topic, PastQuestion.topic_id == Topic.id)
                         .where(PastQuestion.subject_id == subject.id)
                         .order_by(PastQuestion.year.desc().nulls_last(), PastQuestion.id)).all()
    items = [{"id": f"P{p.id}", "text": p.text, "year": p.year, "marks": p.marks,
              "topic_id": t.id if t else None, "topic": (t.title or t.source) if t else None} for p, t in rows]
    if not query or not query.strip():
        return items[:top_k]
    hits = BM25Index([{**it, "content": it["text"]} for it in items], tokenizer=search_tokenize).search(query, limit=top_k)
    return [{k: v for k, v in h.items() if k != "content"} | {"score": round(h["score"], 3)} for h in hits]
