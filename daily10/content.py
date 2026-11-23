"""
Turning a subject's files into study material.

Notes -> topics: the text is chunked (same recursive splitter as the chatbot) and consecutive
chunks are grouped into topics of about TOPIC_CHARS characters, kept in syllabus order. Each
topic is one day's new material: a few pages of notes.

Past papers -> exam weight: each paper is split into individual questions (numbering like
"1.", "Q2", "3 a)", with marks like "(10 Marks)"), and every question is matched to the topic
whose notes it is most about, using BM25 keyword search over the topics (no LLM or embedding
calls). A topic's exam weight is how many past questions matched it.
"""

import re

from daily10.textproc import chunk_text
from daily10.textproc import BM25Index

TOPIC_CHARS = 3000

# A question starts a line with "1.", "1)", "Q1", "Q.1", "1a)", "1. a)", "a)", "(b)" or "(ii)".
_QUESTION_START = re.compile(
    r"(?im)^\s*(?:"
    r"(?:Q\s*\.?\s*\d{1,2}\s*[.)]?|\d{1,2}\s*[.)]|\d{1,2}\s*[a-e]\s*[.)])(?:\s*\(?[a-e]\))?"
    r"|\(?[a-e]\)|\([ivx]{1,4}\)"
    r")\s+"
)
_MARKS = re.compile(r"[\(\[]?\s*(\d{1,2})\s*(?:marks?|m)\s*[\)\]]?\s*$", re.I)
_YEAR = re.compile(r"(?<!\d)(19|20)(\d{2})(?!\d)")


def read_file(path: str) -> str:
    """Text of a notes or paper file (PDF, DOCX, PPTX, HTML, TXT), via the chatbot's loaders."""
    from daily10.loaders import extract_text

    text = extract_text(path)
    if text is None:
        raise ValueError(f"Unsupported file type: {path}")
    return text


def split_into_topics(text: str, source: str, target_chars: int = TOPIC_CHARS) -> list[dict]:
    """[{source, text}] in order, each about `target_chars` long."""
    topics: list[dict] = []
    current: list[str] = []
    for chunk in chunk_text(text):
        current.append(chunk)
        if sum(len(c) for c in current) >= target_chars:
            topics.append(current)
            current = []
    if current:
        if topics and sum(len(c) for c in current) < target_chars / 3:
            topics[-1].extend(current)  # don't leave a tiny last topic
        else:
            topics.append(current)
    return [{"source": f"{source}, part {i}", "text": "\n\n".join(parts)} for i, parts in enumerate(topics, 1)]


def year_from_name(name: str) -> int | None:
    m = _YEAR.search(name)
    return int(m.group(0)) if m else None


def split_past_paper(text: str) -> list[dict]:
    """[{text, marks}] for each question in an exam paper."""
    starts = [m.start() for m in _QUESTION_START.finditer(text)]
    pieces = [text[a:b] for a, b in zip(starts, [*starts[1:], len(text)])] if starts else []
    questions = []
    for piece in pieces:
        body = _QUESTION_START.sub("", piece, count=1).strip()
        body = re.sub(r"\s+", " ", body)
        marks_match = _MARKS.search(body)
        marks = int(marks_match.group(1)) if marks_match else None
        if marks_match:
            body = body[: marks_match.start()].strip()
        if len(body) >= 15 and re.search(r"[a-zA-Z]{3}", body):
            questions.append({"text": body, "marks": marks})
    return questions


def match_to_topics(questions: list[str], topics: list[dict]) -> list[int | None]:
    """For each question, the index of the best-matching topic (None if nothing matches)."""
    index = BM25Index([{"source": "t", "chunk_index": i, "content": t["text"]} for i, t in enumerate(topics)])
    matches = []
    for q in questions:
        hits = index.search(q, limit=1)
        matches.append(hits[0]["chunk_index"] if hits else None)
    return matches
