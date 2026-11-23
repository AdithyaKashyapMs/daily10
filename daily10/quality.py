"""
Question quality checks, used by faculty review and by evals/question_quality.py.

The evidence check at generation time only confirms the quote exists in the notes. That misses
questions whose quote is real but doesn't support the answer (e.g. a YAML line quoted for a
question about what the field means). So every generated question also gets an independent
check: a different model family answers it blind, from the notes only, and reports whether
another option is also defensible or the notes don't answer it. Failing questions stay drafts,
marked "AI check flagged: ..." so faculty look at them first.
"""

import json
import re
import time

from pydantic import BaseModel, Field, ValidationError

_WORD = re.compile(r"[a-z0-9]+")
PASSED = "AI check passed"
FLAGGED = "AI check flagged"


def _words(t: str) -> set[str]:
    return set(_WORD.findall(t.lower()))


def automatic_issues(q: dict, same_topic: list[dict]) -> list[str]:
    from daily10.generate import evidence_found

    issues = []
    opts = q["options"]
    if len(opts) != 4 or len({o.strip().lower() for o in opts}) != 4:
        issues.append("options not 4 distinct")
    if not 0 <= q["answer_index"] < len(opts):
        issues.append("invalid answer index")
    if not evidence_found(q["evidence"], q["notes"]):
        issues.append("evidence not in notes")
    if any(re.search(r"\b(all|none|both) of the (above|these)\b", o, re.I) for o in opts):
        issues.append("all/none-of-the-above option")
    mine = _words(q["prompt"])
    for other in same_topic:
        if other["id"] < q["id"]:
            theirs = _words(other["prompt"])
            if mine and len(mine & theirs) / len(mine | theirs) > 0.8:
                issues.append(f"near-duplicate of question {other['id']}")
                break
    return issues


# --- 2. Independent judge --------------------------------------------------------------------

class Verdict(BaseModel):
    chosen_index: int = Field(description="Index 0-3 of the option the notes support as correct, or -1 if none")
    another_option_also_correct: bool
    answerable_from_notes: bool
    clear: bool = Field(description="The question is unambiguous and well written")
    note: str = ""


JUDGE_PROMPT = """You are checking a multiple-choice question written for engineering students.
Use ONLY the lecture notes below, not outside knowledge.

NOTES:
{notes}

QUESTION: {prompt}
OPTIONS:
{options}

Reply with one JSON object:
- "chosen_index": the index (0-3) of the option the notes support as correct, or -1 if none is
- "another_option_also_correct": true if a second option could also be defended from the notes
- "answerable_from_notes": true if the notes contain enough to answer it
- "clear": true if the question is unambiguous and well written
- "note": one short sentence on any problem, else ""
"""


def judge(questions: list[dict], llm, progress: bool = False) -> dict[int, dict]:
    verdicts = {}
    for i, q in enumerate(questions, 1):
        options = "\n".join(f"{k}. {o}" for k, o in enumerate(q["options"]))
        prompt = JUDGE_PROMPT.format(notes=q["notes"][:6000], prompt=q["prompt"], options=options)
        for attempt in range(4):
            try:
                v = Verdict.model_validate(json.loads(llm.invoke(prompt).content))
                verdicts[q["id"]] = v.model_dump()
                break
            except (ValueError, ValidationError) as e:  # bad JSON: retry once more, then record
                if attempt >= 1:
                    verdicts[q["id"]] = {"error": str(e)[:200]}
                    break
            except Exception as e:  # rate limits on the free tier: wait and retry
                if attempt == 3:
                    verdicts[q["id"]] = {"error": str(e)[:200]}
                else:
                    time.sleep(20 * (attempt + 1))
        if progress:
            print(f"\r  judged {i}/{len(questions)}", end="", flush=True)
    if progress:
        print()
    return verdicts


def judge_correct(q: dict, v: dict) -> bool | None:
    if "error" in v:
        return None
    return (v["chosen_index"] == q["answer_index"] and not v["another_option_also_correct"]
            and v["answerable_from_notes"])




def flag_reason(q: dict, v: dict) -> str | None:
    """Plain-language reason a question needs attention, or None if the judge agrees."""
    if "error" in v:
        return None
    if not v["answerable_from_notes"]:
        return "the notes don't explain this; the answer may come from outside knowledge"
    if v["another_option_also_correct"]:
        return "another option could also be correct"
    if v["chosen_index"] != q["answer_index"]:
        return f"an independent check chose option {chr(65 + v['chosen_index'])}" if 0 <= v["chosen_index"] < 4 else "an independent check found no correct option"
    return None
