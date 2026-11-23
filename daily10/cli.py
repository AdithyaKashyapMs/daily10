"""
Faculty/admin setup from the terminal.

    python -m daily10.cli create-subject 21CS53 "Database Management Systems" --dept CSE --sem 5
    python -m daily10.cli add-notes 21CS53 notes/unit1.pdf notes/unit2.pdf
    python -m daily10.cli add-paper 21CS53 papers/dbms_2023.pdf          # year read from the name
    python -m daily10.cli generate 21CS53 --limit 5                       # LLM: summaries + questions
    python -m daily10.cli topics 21CS53                                   # exam weight per topic
    python -m daily10.cli check 21CS53                                     # independent AI check of drafts
    python -m daily10.cli review 21CS53                                    # approve / reject drafts
"""

import argparse
import sys

from daily10 import content, service


def _review(code: str) -> None:
    drafts = service.list_questions(code, "draft")
    print(f"{len(drafts)} draft question(s). For each: [a]pprove, [r]eject, [s]kip, [q]uit.\n")
    for q in drafts:
        print(f"[{q['topic']}] {q['prompt']}" + (f"   ⚠ {q['status_reason']}" if q['status_reason'].startswith("AI check flagged") else ""))
        for i, opt in enumerate(q["options"]):
            print(f"   {'✓' if i == q['answer_index'] else ' '} {chr(65 + i)}. {opt}")
        print(f"   evidence: \"{q['evidence']}\"")
        choice = input("   > ").strip().lower()[:1]
        if choice == "q":
            return
        if choice in ("a", "r"):
            service.set_question_status(q["id"], "approved" if choice == "a" else "rejected")
        print()


def main(argv=None) -> None:
    p = argparse.ArgumentParser(description="Daily 10 setup")
    sub = p.add_subparsers(dest="cmd", required=True)
    c = sub.add_parser("create-subject"); c.add_argument("code"); c.add_argument("name")
    c.add_argument("--dept", default=""); c.add_argument("--sem", type=int, default=0)
    n = sub.add_parser("add-notes"); n.add_argument("code"); n.add_argument("files", nargs="+")
    a = sub.add_parser("add-paper"); a.add_argument("code"); a.add_argument("file"); a.add_argument("--year", type=int)
    g = sub.add_parser("generate"); g.add_argument("code"); g.add_argument("--limit", type=int)
    t = sub.add_parser("topics"); t.add_argument("code")
    r = sub.add_parser("review"); r.add_argument("code")
    k = sub.add_parser("check"); k.add_argument("code"); k.add_argument("--recheck", action="store_true")
    args = p.parse_args(argv)

    if args.cmd == "create-subject":
        s = service.create_subject(args.code, args.name, args.dept, args.sem)
        print(f"Created {s.code}: {s.name}")
    elif args.cmd == "add-notes":
        texts = [(f.rsplit("/", 1)[-1], content.read_file(f)) for f in args.files]
        print(f"Added {service.add_notes(args.code, texts)} topic(s).")
    elif args.cmd == "add-paper":
        year = args.year or content.year_from_name(args.file)
        print(f"Found {service.add_past_paper(args.code, content.read_file(args.file), year)} question(s).")
    elif args.cmd == "generate":
        from daily10.llm import get_json_llm

        print(service.generate_questions(args.code, get_json_llm(), limit=args.limit))
    elif args.cmd == "topics":
        for t in service.topic_overview(args.code):
            print(f"{t['position']:>3}. {t['title'][:60]:<60} asked {t['exam_weight']}x  {t['questions']}")
    elif args.cmd == "review":
        _review(args.code)
    elif args.cmd == "check":
        from daily10 import config
        from daily10.llm import get_json_llm

        print(service.check_questions(args.code, get_json_llm(models=[config.JUDGE_MODEL, *config.FALLBACK_MODELS]), args.recheck))


if __name__ == "__main__":
    sys.exit(main())
