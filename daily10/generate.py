"""
Topic -> title, summary, key points and multiple-choice questions, grounded in the notes.

The LLM gets only the topic's own notes and must return a JSON object matching TopicPack
(JSON mode: the provider guarantees JSON; Pydantic checks the shape). Every question must
include `evidence`, a short quote copied from the notes that justifies the right answer.

Grounding check (no extra LLM call): the evidence must actually appear in the notes
(whitespace/case-insensitive), or at least 80% of its words must. A question that fails is
saved as `auto_rejected` with the reason, so faculty can still see it, but students never
do. Passing questions are `draft` until a faculty member approves them.

Generation runs once per topic per semester, shared by every student, so LLM cost scales
with the number of subjects, not students.
"""

import json
import re

import logging
from pydantic import BaseModel, Field, ValidationError, field_validator

log = logging.getLogger(__name__)


QUESTIONS_PER_TOPIC = 6
_WORD = re.compile(r"[a-z0-9]+")


class GeneratedQuestion(BaseModel):
    question: str
    options: list[str] = Field(description="Exactly 4 answer options")
    answer_index: int = Field(description="Index (0-3) of the correct option")
    explanation: str = Field(description="One or two sentences on why it is correct")
    evidence: str = Field(description="A short quote copied word for word from the notes that supports the answer")

    @field_validator("options")
    @classmethod
    def _four_options(cls, v: list[str]) -> list[str]:
        v = [o.strip() for o in v if o and o.strip()]
        if len(v) != 4 or len(set(o.lower() for o in v)) != 4:
            raise ValueError("need exactly 4 distinct options")
        return v

    @field_validator("answer_index")
    @classmethod
    def _valid_index(cls, v: int) -> int:
        if not 0 <= v <= 3:
            raise ValueError("answer_index must be 0-3")
        return v


class TopicPack(BaseModel):
    title: str = Field(description="Short topic title, at most 8 words")
    summary: str = Field(description="Plain-language summary of the notes, at most 120 words")
    key_points: list[str] = Field(description="3 to 5 key points to remember")
    questions: list[GeneratedQuestion]


PROMPT = """You are helping engineering students revise for exams, 10 minutes a day.
Below are the lecture notes for one topic. Using ONLY these notes:

1. A short title (max 8 words).
2. A plain-language summary (max 120 words) a student can read in 2 minutes.
3. 3 to 5 key points to remember.
4. {n} multiple-choice questions that test understanding, not trivia. Each has exactly 4
   options, one correct answer, a 1-2 sentence explanation, and "evidence": a short quote
   copied word for word from the notes that supports the correct answer.

Do not use facts that are not in the notes. Reply with one JSON object with keys
"title", "summary", "key_points", "questions" (each question: "question", "options",
"answer_index", "explanation", "evidence").

NOTES:
{notes}"""


def _words(text: str) -> list[str]:
    return _WORD.findall(text.lower())


def evidence_found(evidence: str, notes: str, min_overlap: float = 0.8) -> bool:
    """Is the quote in the notes? Exact (ignoring case/spacing), or ≥80% of its words present."""
    ev, nt = " ".join(_words(evidence)), " ".join(_words(notes))
    if len(ev) < 12:
        return False
    if ev in nt:
        return True
    words = _words(evidence)
    note_words = set(_words(notes))
    return sum(w in note_words for w in words) / len(words) >= min_overlap


def grounding_issue(q: GeneratedQuestion, notes: str) -> str | None:
    """Why this question can't be trusted, or None if it passes."""
    if not evidence_found(q.evidence, notes):
        return "evidence quote not found in the notes"
    return None


def generate_pack(notes: str, llm, n_questions: int = QUESTIONS_PER_TOPIC, attempts: int = 2) -> TopicPack:
    """Ask the LLM (JSON mode) for a TopicPack; retry once if the JSON doesn't match the schema."""
    error = None
    for _ in range(attempts):
        raw = llm.invoke(PROMPT.format(n=n_questions, notes=notes)).content
        try:
            data = json.loads(raw)
            # Drop malformed questions individually instead of rejecting the whole topic.
            good = []
            for q in data.get("questions", []):
                try:
                    good.append(GeneratedQuestion.model_validate(q))
                except ValidationError as e:
                    log.warning(f"Dropped malformed generated question: {e.errors()[0]['msg']}")
            data["questions"] = good
            return TopicPack.model_validate(data)
        except (ValueError, ValidationError) as e:
            error = e
            log.warning(f"Topic generation returned invalid JSON, retrying: {e}")
    raise ValueError(f"Could not generate a valid topic pack: {error}")
