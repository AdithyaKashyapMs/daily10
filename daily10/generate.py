"""
Topic -> title, summary, key points and multiple-choice questions, grounded in the notes.

The LLM gets only the topic's own notes and must return a JSON object matching TopicPack
(JSON mode: the provider guarantees JSON; Pydantic checks the shape). Every question must
include `evidence`, a short quote copied from the notes that justifies the right answer.

Grounding check (no extra LLM call): the evidence must actually appear in the notes
(whitespace/case-insensitive), or at least 80% of its words must. A question that fails is
saved as `auto_rejected` with the reason, so faculty can still see it, but students never
do. Passing questions are `draft` until a faculty member approves them.

Each pack also has an "explain simply" layer: a plain-language explanation, an everyday
analogy and a glossary of the topic's technical terms. Glossary terms must appear in the notes
(others are dropped); the explanation and analogy can't be checked mechanically, so they wait for
faculty review like questions do. Questions are tagged warmup (what a term means), core
(understanding) or exam (applying it, past-paper style), so a session can climb that ladder.

Generation runs once per topic per semester, shared by every student, so LLM cost scales
with the number of subjects, not students.
"""

import json
import re

import logging
from pydantic import BaseModel, Field, ValidationError, field_validator

log = logging.getLogger(__name__)


QUESTIONS_PER_TOPIC = 6
LEVELS = ("warmup", "core", "exam")
GLOSSARY_MAX = 8
_WORD = re.compile(r"[a-z0-9]+")


class GeneratedQuestion(BaseModel):
    question: str
    options: list[str] = Field(description="Exactly 4 answer options")
    answer_index: int = Field(description="Index (0-3) of the correct option")
    explanation: str = Field(description="One or two sentences on why it is correct")
    evidence: str = Field(description="A short quote copied word for word from the notes that supports the answer")
    level: str = Field("core", description="warmup | core | exam")

    @field_validator("level", mode="before")
    @classmethod
    def _level(cls, v) -> str:
        v = str(v or "core").strip().lower().replace("-", "").replace(" ", "")
        return v if v in LEVELS else "core"

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


class GlossaryTerm(BaseModel):
    term: str
    meaning: str


class SimpleLayer(BaseModel):
    simple_explanation: str = Field("", description="The topic in everyday words, no jargon, at most 80 words")
    analogy: str = Field("", description="One everyday analogy, 1-2 sentences")
    glossary: list[GlossaryTerm] = Field(default_factory=list, description="Technical terms with one-line plain meanings")

    def has_content(self) -> bool:
        return bool(self.simple_explanation.strip() or self.glossary)


class TopicPack(SimpleLayer):
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
   copied word for word from the notes that supports the correct answer. Give each a "level":
   "warmup" (what a term means), "core" (why or how it works) or "exam" (apply it, as an
   exam would). Write about a third at each level.
{simple}
Do not use facts that are not in the notes. Reply with one JSON object with keys
"title", "summary", "key_points", "simple_explanation", "analogy", "glossary", "questions"
(each question: "question", "options", "answer_index", "explanation", "evidence", "level";
each glossary entry: "term", "meaning").

NOTES:
{notes}"""


SIMPLE_TASK = """5. "simple_explanation": the same topic for a student who finds the technical words hard:
   everyday language, short sentences, no jargon, at most 80 words.
6. "analogy": one everyday analogy (1-2 sentences) that matches how the notes describe it.
   Don't stretch it beyond what the notes say.
7. "glossary": up to 8 technical terms that appear in the notes, each with a one-line meaning
   in plain words.
"""

SIMPLE_PROMPT = """You are helping engineering students who find technical terms hard to follow.
Below are the lecture notes for one topic. Using ONLY these notes, write:

""" + SIMPLE_TASK.replace("5. ", "1. ").replace("6. ", "2. ").replace("7. ", "3. ") + """
{questions}Reply with one JSON object with keys "simple_explanation", "analogy", "glossary"{levels_key}
(each glossary entry: "term", "meaning").

NOTES:
{notes}"""

LEVELS_TASK = """4. "levels": this topic's existing questions are below. Tag each one: "warmup" (what a term
   means), "core" (why or how it works) or "exam" (apply it, as an exam would). Reply as an
   object from question id to level, e.g. {{"12": "warmup"}}.

QUESTIONS:
{listing}

"""


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


def grounded_glossary(terms: list[GlossaryTerm], notes: str) -> list[GlossaryTerm]:
    """Glossary entries whose term appears in the notes, de-duplicated, at most GLOSSARY_MAX."""
    text = " " + " ".join(_words(notes)) + " "
    out, seen = [], set()
    for t in terms:
        key = " ".join(_words(t.term))
        if key and key not in seen and t.meaning.strip() and f" {key} " in text:
            seen.add(key)
            out.append(GlossaryTerm(term=t.term.strip(), meaning=t.meaning.strip()))
    return out[:GLOSSARY_MAX]


def _parse_glossary(data: dict) -> None:
    """Keep the well-formed glossary entries, so one bad entry doesn't sink the whole pack."""
    good = []
    for g in data.get("glossary") or []:
        try:
            good.append(GlossaryTerm.model_validate(g))
        except ValidationError:
            continue
    data["glossary"] = good


def generate_simple(notes: str, llm, questions: list[tuple[int, str]] | None = None,
                    attempts: int = 2) -> tuple[SimpleLayer, dict[int, str]]:
    """
    Only the "explain simply" layer, for topics generated before it existed. If `questions`
    ((id, prompt) pairs) are given, the same call tags their levels: {id: level} for known ids.
    """
    extra = ""
    if questions:
        listing = "\n".join(f"{qid}: {prompt}" for qid, prompt in questions)
        extra = LEVELS_TASK.format(listing=listing)
    prompt = SIMPLE_PROMPT.format(notes=notes, questions=extra, levels_key=', "levels"' if questions else "")
    known = {qid for qid, _ in questions or []}
    error = None
    for _ in range(attempts):
        try:
            data = json.loads(llm.invoke(prompt).content)
            _parse_glossary(data)
            layer = SimpleLayer.model_validate({k: data.get(k) or v for k, v in
                                                (("simple_explanation", ""), ("analogy", ""), ("glossary", []))})
            layer.glossary = grounded_glossary(layer.glossary, notes)
            levels = {}
            raw = data.get("levels") if isinstance(data.get("levels"), dict) else {}
            for k, v in raw.items():
                qid = int(k) if str(k).strip().isdigit() else None
                level = str(v).strip().lower().replace("-", "").replace(" ", "")
                if qid in known and level in LEVELS:
                    levels[qid] = level
            return layer, levels
        except (ValueError, ValidationError) as e:
            error = e
            log.warning(f"Simple-layer generation returned invalid JSON, retrying: {e}")
    raise ValueError(f"Could not generate a simple explanation: {error}")


def generate_pack(notes: str, llm, n_questions: int = QUESTIONS_PER_TOPIC, attempts: int = 2) -> TopicPack:
    """Ask the LLM (JSON mode) for a TopicPack; retry once if the JSON doesn't match the schema."""
    error = None
    for _ in range(attempts):
        raw = llm.invoke(PROMPT.format(n=n_questions, notes=notes, simple=SIMPLE_TASK)).content
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
            _parse_glossary(data)
            for key in ("simple_explanation", "analogy"):
                data[key] = data.get(key) or ""
            pack = TopicPack.model_validate(data)
            pack.glossary = grounded_glossary(pack.glossary, notes)
            return pack
        except (ValueError, ValidationError) as e:
            error = e
            log.warning(f"Topic generation returned invalid JSON, retrying: {e}")
    raise ValueError(f"Could not generate a valid topic pack: {error}")
