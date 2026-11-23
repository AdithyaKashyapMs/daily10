"""
How many generated questions are actually correct?

Three layers, so the number isn't just "the AI grading itself":

1. Automatic checks (no LLM): exactly 4 distinct options, a valid answer index, the evidence
   quote really appears in the notes, no near-duplicate question in the same topic, and no
   "all/none of the above" options.

2. Independent judge (a different model family, JSON mode). It answers each question BLIND,
   using only the topic's notes, without seeing the marked answer, and reports whether more
   than one option is defensible or the notes don't answer it. A question counts as correct
   when the judge picks the marked answer, finds exactly one right option, and the notes
   answer it.

3. Human labels (`label` command): a person marks a sample correct / wrong. The report then
   shows the human-labelled accuracy and how well the judge agrees with the human, which is
   what says whether the judge's number can be trusted.

Usage:
    python -m evals.question_quality judge  CC701            # automatic checks + judge
    python -m evals.question_quality label  CC701 --n 40     # you label a random sample
    python -m evals.question_quality report CC701            # numbers, incl. judge vs human
"""

import argparse
import json
import os
import random
import sys
from datetime import date

from sqlalchemy import select

from daily10.quality import automatic_issues, judge, judge_correct

HERE = os.path.dirname(__file__)
RESULTS = os.path.join(HERE, "results")
LABELS = os.path.join(HERE, "human_labels.json")
def load_questions(subject_code: str) -> list[dict]:
    """Every generated question for the subject (any review status), with its topic's notes."""
    from daily10 import db
    from daily10.db import Question, Subject, Topic

    with db.session() as s:
        subject = s.scalar(select(Subject).where(Subject.code == subject_code.upper()))
        if subject is None:
            sys.exit(f"No subject {subject_code}")
        rows = s.execute(select(Question, Topic).join(Topic).where(Topic.subject_id == subject.id)
                         .order_by(Topic.position, Question.id)).all()
        return [{"id": q.id, "topic_id": t.id, "topic": t.title or t.source, "notes": t.text, "prompt": q.prompt,
                 "options": q.options, "answer_index": q.answer_index, "evidence": q.evidence,
                 "status": q.status} for q, t in rows]


# --- 1. Automatic checks ---------------------------------------------------------------------

# --- 3. Human labels -------------------------------------------------------------------------

def label(questions: list[dict], n: int, seed: int = 7) -> None:
    labels = json.load(open(LABELS)) if os.path.exists(LABELS) else {}
    todo = [q for q in questions if str(q["id"]) not in labels]
    random.Random(seed).shuffle(todo)
    print(f"{len(labels)} labelled so far. For each: [y] correct  [n] wrong  [s] skip  [q] quit\n"
          "Correct = the marked answer is right according to the notes, and no other option is.\n")
    for q in todo[:n]:
        print(f"[{q['topic']}]  #{q['id']}\n{q['prompt']}")
        for k, o in enumerate(q["options"]):
            print(f"   {'→' if k == q['answer_index'] else ' '} {k}. {o}")
        print(f"   evidence: \"{q['evidence'][:200]}\"")
        a = input("   correct? > ").strip().lower()[:1]
        if a == "q":
            break
        if a in ("y", "n"):
            labels[str(q["id"])] = a == "y"
            json.dump(labels, open(LABELS, "w"), indent=1)
        print()
    print(f"Saved {len(labels)} labels to {LABELS}")


# --- Report ----------------------------------------------------------------------------------

def report(subject_code: str) -> dict:
    path = os.path.join(RESULTS, f"question_quality_{subject_code.upper()}.json")
    data = json.load(open(path))
    questions = {q["id"]: q for q in data["questions"]}
    labels = {int(k): v for k, v in (json.load(open(LABELS)).items() if os.path.exists(LABELS) else [])}

    judged = [q for q in questions.values() if q["judge_correct"] is not None]
    out = {
        "questions": len(questions),
        "topics": len({q["topic_id"] for q in questions.values()}),
        "passed_automatic_checks": round(sum(not q["auto_issues"] for q in questions.values()) / len(questions), 3),
        "judge_correct": round(sum(q["judge_correct"] for q in judged) / len(judged), 3) if judged else None,
        "judge_errors": len(questions) - len(judged),
        "judge_flags": {
            "different_answer": sum(q["verdict"].get("chosen_index") != q["answer_index"] for q in judged),
            "two_defensible_options": sum(q["verdict"].get("another_option_also_correct", False) for q in judged),
            "not_answerable_from_notes": sum(not q["verdict"].get("answerable_from_notes", True) for q in judged),
            "unclear": sum(not q["verdict"].get("clear", True) for q in judged),
        },
        "both_checks_passed": round(sum((not q["auto_issues"]) and q["judge_correct"] for q in judged) / len(judged), 3) if judged else None,
    }
    common = [i for i in labels if i in questions and questions[i]["judge_correct"] is not None]
    if labels:
        human = [labels[i] for i in labels if i in questions]
        out["human"] = {"labelled": len(human), "correct": round(sum(human) / len(human), 3) if human else None}
    if common:
        agree = sum(labels[i] == questions[i]["judge_correct"] for i in common)
        bad = [i for i in common if not labels[i]]
        caught = sum(not questions[i]["judge_correct"] for i in bad)
        false_alarms = sum((not questions[i]["judge_correct"]) for i in common if labels[i])
        out["judge_vs_human"] = {
            "compared": len(common),
            "agreement": round(agree / len(common), 3),
            "wrong_questions_caught_by_judge": f"{caught}/{len(bad)}",
            "correct_questions_flagged_by_judge": f"{false_alarms}/{len(common) - len(bad)}",
        }
    return out


def main() -> None:
    p = argparse.ArgumentParser(description="Generated question quality")
    p.add_argument("command", choices=["judge", "label", "report"])
    p.add_argument("subject")
    p.add_argument("--n", type=int, default=40, help="questions to label")
    args = p.parse_args()

    if args.command == "label":
        return label(load_questions(args.subject), args.n)
    if args.command == "judge":
        from daily10 import config
        from daily10.llm import get_json_llm

        questions = load_questions(args.subject)
        by_topic: dict[int, list[dict]] = {}
        for q in questions:
            by_topic.setdefault(q["topic_id"], []).append(q)
        for q in questions:
            q["auto_issues"] = automatic_issues(q, by_topic[q["topic_id"]])
        print(f"Judging {len(questions)} questions with {config.JUDGE_MODEL} (blind, notes only)...")
        verdicts = judge(questions, get_json_llm(models=[config.JUDGE_MODEL, *config.FALLBACK_MODELS]), progress=True)
        for q in questions:
            q["verdict"] = verdicts.get(q["id"], {"error": "not judged"})
            q["judge_correct"] = judge_correct(q, q["verdict"])
            q.pop("notes")
        os.makedirs(RESULTS, exist_ok=True)
        path = os.path.join(RESULTS, f"question_quality_{args.subject.upper()}.json")
        json.dump({"date": date.today().isoformat(), "judge_model": config.JUDGE_MODEL,
                   "generator_model": config.MODEL, "questions": questions}, open(path, "w"), indent=1)
        print(f"Saved {path}")
    print(json.dumps(report(args.subject), indent=2))


if __name__ == "__main__":
    main()
