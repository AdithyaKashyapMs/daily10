"use client";

import Link from "next/link";
import { useRouter } from "next/navigation";
import { useCallback, useEffect, useState } from "react";
import { api, type AnswerResult, type Level, type Profile, type Session } from "@/lib/api";
import { useStudent } from "@/lib/session";
import { Loading, StudentFrame } from "@/components/BottomNav";
import SimpleExplanation from "@/components/SimpleExplanation";
import Snappy from "@/components/Snappy";

type Step = { kind: "card" } | { kind: "question"; index: number } | { kind: "past" } | { kind: "done" };
const LETTERS = ["A", "B", "C", "D"];
const LEVELS: Record<Level, { label: string; tint: string }> = {
  warmup: { label: "🌱 Warm-up", tint: "bg-mint-soft" },
  core: { label: "📘 Core", tint: "bg-sun-soft" },
  exam: { label: "🎯 Exam-style", tint: "bg-tomato-soft" },
};

function firstStep(s: Session): Step {
  const open = s.questions.findIndex((q) => !q.answered);
  if (s.completed || (s.questions.length > 0 && open === -1)) return s.past_question ? { kind: "past" } : { kind: "done" };
  if (open > 0) return { kind: "question", index: open };
  if (s.card) return { kind: "card" };
  if (s.questions.length) return { kind: "question", index: 0 };
  return { kind: "done" };
}

export default function Today() {
  const ready = useStudent();
  const router = useRouter();
  const [session, setSession] = useState<Session | null>(null);
  const [profile, setProfile] = useState<Profile | null>(null);
  const [error, setError] = useState("");
  const [step, setStep] = useState<Step>({ kind: "card" });
  const [results, setResults] = useState<Record<number, AnswerResult & { chosen: number }>>({});
  const [busy, setBusy] = useState(false);
  const [reported, setReported] = useState<Set<number>>(new Set());
  const [simpleView, setSimpleView] = useState(false);

  const load = useCallback(async () => {
    if (!ready) return;
    setError("");
    try {
      const [s, p] = await Promise.all([api.today(), api.profile()]);
      if (p.needs_profile) return router.replace("/auth/student?step=profile");
      setSession(s);
      setProfile(p);
      setStep(firstStep(s));
      setSimpleView(Boolean(s.card?.simple && s.card.start_simple));
    } catch (e) {
      setError((e as Error).message);
    }
  }, [ready, router]);

  useEffect(() => {
    load();
  }, [load]);

  const total = session?.questions.length ?? 0;
  const answeredNow = Object.values(results);

  async function choose(qid: number, index: number) {
    if (results[qid] || busy) return;
    setBusy(true);
    try {
      const r = await api.answer(qid, index);
      setResults((prev) => ({ ...prev, [qid]: { ...r, chosen: index } }));
    } catch (e) {
      setError((e as Error).message);
    } finally {
      setBusy(false);
    }
  }

  function next() {
    if (!session) return;
    const afterQuestions: Step = session.past_question ? { kind: "past" } : { kind: "done" };
    if (step.kind === "card") return setStep(total ? { kind: "question", index: 0 } : afterQuestions);
    if (step.kind === "question") {
      const after = session.questions.findIndex((q, i) => i > step.index && !q.answered && !results[q.id]);
      return setStep(after !== -1 ? { kind: "question", index: after } : afterQuestions);
    }
    if (step.kind === "past") setStep({ kind: "done" });
  }

  async function report(qid: number) {
    try {
      await api.report(qid);
      setReported((prev) => new Set(prev).add(qid));
    } catch (e) {
      setError((e as Error).message);
    }
  }

  const day = session ? new Date(session.day + "T00:00:00").toLocaleDateString(undefined, { weekday: "long", day: "numeric", month: "short" }) : "";

  let body: React.ReactNode;
  if (!ready || (!session && !error)) {
    body = <Loading label="Getting today's 10 minutes ready…" />;
  } else if (!session) {
    body = (
      <div className="alert alert-error">
        {error} <button onClick={load} className="ml-1 font-extrabold underline">Try again</button>
      </div>
    );
  } else if (profile && profile.subjects.length === 0) {
    body = (
      <div className="sticker-lg overflow-hidden">
        <div className="block-sky flex items-end gap-3 border-b-[3px] border-ink px-5 pt-4">
          <Snappy pose="confused" size={90} bob={false} />
          <p className="pb-4 font-display text-xl font-bold">No subjects yet!</p>
        </div>
        <div className="p-5">
          <p className="font-semibold text-ink-soft">Add your subjects and exam dates. Daily 10 spreads the syllabus over the days you have.</p>
          <Link href="/settings" className="btn btn-primary btn-block btn-lg mt-4">Add subjects</Link>
        </div>
      </div>
    );
  } else if (step.kind === "card" && session.card) {
    const c = session.card;
    body = (
      <>
        <article className="sticker-lg overflow-hidden">
          <div className="block-sun flex items-end gap-3 border-b-[3px] border-ink px-5 pt-3">
            <Snappy pose="book" size={86} bob={false} />
            <div className="pb-3">
              <span className="chip">{c.subject}</span>
              {c.exam_weight > 0 && <span className="chip ml-1 mt-1 bg-tomato-soft">📝 asked {c.exam_weight}× in exams</span>}
            </div>
          </div>
          <div className="p-5">
            <h2 className="font-display text-3xl font-extrabold leading-tight">{c.title}</h2>
            {c.simple && (
              <div className="mt-3 flex gap-2" role="tablist" aria-label="Explanation style">
                {[
                  { simple: false, label: "📖 Full" },
                  { simple: true, label: "🧩 Explain simply" },
                ].map((t) => (
                  <button
                    key={t.label}
                    role="tab"
                    aria-selected={simpleView === t.simple}
                    onClick={() => setSimpleView(t.simple)}
                    className={`chip cursor-pointer ${simpleView === t.simple ? "bg-ink text-white" : "bg-white"}`}
                  >
                    {t.label}
                  </button>
                ))}
              </div>
            )}
            {c.simple && simpleView ? (
              <div className="mt-3">
                <SimpleExplanation layer={c.simple} />
              </div>
            ) : (
              <>
                {c.summary ? <p className="mt-3 font-semibold leading-relaxed text-ink/85">{c.summary}</p> : <p className="mt-3 text-ink-soft">Summary not ready yet.</p>}
                {c.key_points?.length > 0 && (
                  <ul className="mt-4 space-y-2">
                    {c.key_points.map((p, i) => (
                      <li key={i} className="sticker-flat flex gap-2.5 bg-sun-soft px-3 py-2 font-semibold">
                        <span aria-hidden>⭐</span>
                        {p}
                      </li>
                    ))}
                  </ul>
                )}
              </>
            )}
            <p className="mt-4 text-sm font-semibold text-ink-soft">From your notes: {c.source}</p>
          </div>
        </article>
        <button onClick={next} className="btn btn-primary btn-block btn-lg">{total ? `Start ${total} questions →` : "Continue →"}</button>
      </>
    );
  } else if (step.kind === "question") {
    const q = session.questions[step.index];
    const r = results[q.id];
    body = (
      <>
        <article className="sticker-lg p-5">
          <div className="flex items-center justify-between gap-2">
            <span className="flex flex-wrap gap-1.5">
              <span className={`chip ${q.kind === "new" ? "bg-sky-soft" : "bg-plum-soft"}`}>{q.kind === "new" ? "🆕 New" : "🔁 Review"}</span>
              {q.level && <span className={`chip ${LEVELS[q.level].tint}`}>{LEVELS[q.level].label}</span>}
            </span>
            <span className="font-display text-lg font-extrabold">{step.index + 1}/{total}</span>
          </div>
          <p className="mt-1 text-sm font-semibold text-ink-soft">{q.topic}</p>
          <h2 className="mt-3 font-display text-2xl font-extrabold leading-snug">{q.prompt}</h2>
          <div className="mt-4 space-y-2.5" role="radiogroup" aria-label="Answer options">
            {q.options.map((opt, i) => {
              const right = r && i === r.answer_index;
              const wrong = r && i === r.chosen && !r.correct;
              return (
                <button
                  key={i}
                  role="radio"
                  aria-checked={r?.chosen === i}
                  disabled={!!r || busy}
                  onClick={() => choose(q.id, i)}
                  className={`option ${right ? "option-right" : wrong ? "option-wrong" : ""}`}
                >
                  <span className={`option-letter ${right ? "bg-mint text-white" : wrong ? "bg-tomato text-white" : ""}`}>
                    {right ? "✓" : wrong ? "✕" : LETTERS[i]}
                  </span>
                  {opt}
                </button>
              );
            })}
          </div>
        </article>
        {r && (
          <div className={`sticker pop-in flex gap-3 p-4 ${r.correct ? "bg-mint-soft" : "bg-tomato-soft"}`} aria-live="polite">
            <Snappy pose={r.correct ? "celebrate" : "confused"} size={64} bob={false} className="shrink-0" />
            <div>
              <p className="font-display text-xl font-extrabold">{r.correct ? "Nailed it!" : "Not quite."}</p>
              <p className="mt-1 font-semibold">{r.explanation}</p>
              <p className="mt-2 text-sm font-semibold text-ink-soft">From your notes: “{r.evidence}”</p>
              <p className="mt-1 text-xs font-bold text-ink-soft">
                {r.correct ? "You'll see it again " : "It comes back "}
                {new Date(r.next_review + "T00:00:00").toLocaleDateString(undefined, { weekday: "short", day: "numeric", month: "short" })}
              </p>
            </div>
          </div>
        )}
        {r && !r.correct && r.simple && (
          <div className="sticker pop-in bg-white p-4" aria-live="polite">
            <p className="mb-2 font-display text-xl font-extrabold">🧩 Let&apos;s make it simpler</p>
            <SimpleExplanation layer={r.simple} compact />
          </div>
        )}
        {r && (
          <>
            <button onClick={next} className="btn btn-primary btn-block btn-lg">Next →</button>
            <button onClick={() => report(q.id)} disabled={reported.has(q.id)} className="text-sm font-bold text-ink-soft underline decoration-2 underline-offset-2 disabled:no-underline">
              {reported.has(q.id) ? "Thanks, sent to your faculty" : "This question looks wrong"}
            </button>
          </>
        )}
      </>
    );
  } else if (step.kind === "past" && session.past_question) {
    const p = session.past_question;
    body = (
      <>
        <article className="sticker-lg overflow-hidden">
          <div className="block-plum flex items-end gap-3 border-b-[3px] border-ink px-5 pt-3">
            <Snappy pose="pencil" size={86} bob={false} />
            <p className="pb-4 font-display text-xl font-bold">
              Past exam{p.year ? ` · ${p.year}` : ""}{p.marks ? ` · ${p.marks} marks` : ""}
            </p>
          </div>
          <div className="p-5">
            <h2 className="font-display text-2xl font-extrabold leading-snug">{p.text}</h2>
            <p className="mt-2 font-semibold text-ink-soft">Take 2 minutes: jot down the points you&apos;d write. Only you see this.</p>
            <textarea rows={5} aria-label="Your answer outline" className="input mt-3" placeholder="• First point…" />
          </div>
        </article>
        <button onClick={next} className="btn btn-primary btn-block btn-lg">Finish today 🎉</button>
      </>
    );
  } else {
    const nothing = total === 0 && !session.card;
    const right = answeredNow.filter((r) => r.correct).length;
    body = (
      <div className="sticker-lg overflow-hidden text-center">
        <div className={`${nothing ? "block-sky" : "block-mint"} flex justify-center border-b-[3px] border-ink pt-6`}>
          <Snappy pose={nothing ? "wave" : "celebrate"} size={150} />
        </div>
        <div className="p-6">
          <h2 className="font-display text-3xl font-extrabold">{nothing ? "Nothing due today" : "Done for today!"}</h2>
          {!nothing && answeredNow.length > 0 && <p className="mt-1 text-lg font-bold">{right} of {answeredNow.length} right</p>}
          {session.notes.map((n, i) => (
            <p key={i} className="mt-2 font-semibold text-ink-soft">{n}</p>
          ))}
          {profile && <p className="mt-2 font-semibold text-ink-soft">See you tomorrow at {profile.notify_time}.</p>}
          <Link href="/progress" className="btn btn-sun mt-5">See my streak 🔥</Link>
        </div>
      </div>
    );
  }

  return (
    <StudentFrame>
      <header>
        <p className="font-bold text-ink-soft">{day}</p>
        <h1 className="font-display text-4xl font-extrabold">Today</h1>
      </header>
      {session && total > 0 && step.kind !== "done" && (
        <div className="flex gap-1.5" aria-label="Question progress">
          {session.questions.map((q) => (
            <span
              key={q.id}
              className={`h-3 flex-1 rounded-full border-2 border-ink ${
                results[q.id] ? (results[q.id].correct ? "bg-mint" : "bg-tomato") : q.answered ? "bg-sky" : "bg-white"
              }`}
            />
          ))}
        </div>
      )}
      {step.kind === "card" && session?.notes.map((n, i) => <p key={i} className="alert alert-info">{n}</p>)}
      {error && session && <p className="alert alert-error">{error}</p>}
      {body}
    </StudentFrame>
  );
}
