"use client";

import { useParams } from "next/navigation";
import { useCallback, useEffect, useState } from "react";
import { api, type Explanation, type GlossaryTerm, type Level, type ReviewQuestion } from "@/lib/api";
import { useFaculty } from "@/lib/session";
import FacultyShell from "@/components/FacultyShell";
import Snappy from "@/components/Snappy";

const LETTERS = ["A", "B", "C", "D"];
const LEVELS: { value: Level; label: string }[] = [
  { value: "warmup", label: "🌱 Warm-up: what a term means" },
  { value: "core", label: "📘 Core: why / how it works" },
  { value: "exam", label: "🎯 Exam-style: apply it" },
];

type Tab = "questions" | "simple";

export default function ReviewPage() {
  const me = useFaculty();
  const { code } = useParams<{ code: string }>();
  const [tab, setTab] = useState<Tab>("questions");
  const [drafts, setDrafts] = useState<ReviewQuestion[] | null>(null);
  const [rejected, setRejected] = useState<ReviewQuestion[]>([]);
  const [explanations, setExplanations] = useState<Explanation[] | null>(null);
  const [error, setError] = useState("");
  const [done, setDone] = useState(0);

  const load = useCallback(async () => {
    if (!me) return;
    try {
      const [d, r, e] = await Promise.all([
        api.questions(code, "draft"),
        api.questions(code, "auto_rejected"),
        api.explanations(code, "draft"),
      ]);
      setDrafts(d);
      setRejected(r);
      setExplanations(e);
    } catch (e) {
      setError((e as Error).message);
    }
  }, [me, code]);

  useEffect(() => {
    load();
  }, [load]);

  async function decide(q: ReviewQuestion, status: "approved" | "rejected") {
    if (!me) return;
    try {
      await api.setStatus(q.id, status);
      setDrafts((d) => d?.filter((x) => x.id !== q.id) ?? null);
      setDone((n) => n + 1);
    } catch (e) {
      setError((e as Error).message);
    }
  }

  async function changeLevel(q: ReviewQuestion, level: Level) {
    if (!me) return;
    try {
      const updated = await api.setLevel(q.id, level);
      setDrafts((d) => d?.map((x) => (x.id === q.id ? { ...x, level: updated.level } : x)) ?? null);
    } catch (e) {
      setError((e as Error).message);
    }
  }

  function explanationDone(topicId: number) {
    setExplanations((list) => list?.filter((x) => x.topic_id !== topicId) ?? null);
    setDone((n) => n + 1);
  }

  const tabs: { id: Tab; label: string; count: number | undefined }[] = [
    { id: "questions", label: "Questions", count: drafts?.length },
    { id: "simple", label: "Simple explanations", count: explanations?.length },
  ];

  return (
    <FacultyShell subject={code}>
      <h1 className="font-display text-4xl font-extrabold">Review</h1>
      <p className="mt-1 font-semibold text-ink-soft">
        Students only ever see what you approve. Questions an independent AI check flagged, or students reported, are shown first.
      </p>
      {error && <p className="alert alert-error mt-4">{error}</p>}
      {done > 0 && <p className="alert alert-ok mt-4">{done} reviewed this session.</p>}

      <div className="mt-5 flex flex-wrap gap-2" role="tablist" aria-label="What to review">
        {tabs.map((t) => (
          <button
            key={t.id}
            role="tab"
            aria-selected={tab === t.id}
            onClick={() => setTab(t.id)}
            className={`btn ${tab === t.id ? "btn-primary" : "btn-white"}`}
          >
            {t.label}
            {t.count !== undefined && <span className="chip ml-1 bg-white text-ink">{t.count}</span>}
          </button>
        ))}
      </div>

      {tab === "questions" && (
        <>
          {drafts && drafts.length === 0 && <AllCaughtUp what="questions" />}
          <div className="mt-6 grid gap-5 xl:grid-cols-2">
            {drafts?.map((q) => (
              <article key={q.id} className="sticker-lg flex flex-col p-5">
                <div className="flex flex-wrap items-center gap-2">
                  <span className="chip bg-sky-soft">{q.topic}</span>
                  {q.reports > 0 && <span className="chip bg-tomato-soft">⚠️ reported by {q.reports} student{q.reports === 1 ? "" : "s"}</span>}
                  {q.status_reason.startsWith("AI check passed") && <span className="chip bg-mint-soft">✓ AI check passed</span>}
                </div>
                {q.status_reason.startsWith("AI check flagged") && (
                  <p className="alert alert-warn mt-3">⚠️ Check closely: {q.status_reason.replace("AI check flagged: ", "")}</p>
                )}
                <h2 className="mt-3 font-display text-xl font-extrabold leading-snug">{q.prompt}</h2>
                <ul className="mt-3 space-y-1.5">
                  {q.options.map((o, i) => (
                    <li key={i} className={`sticker-flat flex items-center gap-2 px-3 py-1.5 font-semibold ${i === q.answer_index ? "bg-mint-soft" : ""}`}>
                      <span className="font-display font-extrabold">{i === q.answer_index ? "✓" : LETTERS[i]}</span> {o}
                    </li>
                  ))}
                </ul>
                <p className="mt-3 text-sm font-semibold"><b>Why:</b> {q.explanation}</p>
                <blockquote className="mt-2 border-l-4 border-sun bg-sun-soft px-3 py-2 text-sm font-semibold">“{q.evidence}”</blockquote>
                <label className="mt-3 text-sm font-bold">
                  Level <span className="font-semibold text-ink-soft">(sessions go warm-up → core → exam)</span>
                  <select
                    value={q.level}
                    onChange={(e) => changeLevel(q, e.target.value as Level)}
                    className="input mt-1"
                  >
                    {LEVELS.map((l) => (
                      <option key={l.value} value={l.value}>{l.label}</option>
                    ))}
                  </select>
                </label>
                <div className="mt-4 flex gap-2">
                  <button onClick={() => decide(q, "approved")} className="btn btn-mint flex-1">Approve</button>
                  <button onClick={() => decide(q, "rejected")} className="btn btn-white flex-1">Reject</button>
                </div>
              </article>
            ))}
          </div>

          {rejected.length > 0 && (
            <details className="sticker mt-8 p-5">
              <summary className="cursor-pointer font-display text-xl font-extrabold">Auto-rejected: quote not found in the notes ({rejected.length})</summary>
              <ul className="mt-3 space-y-2">
                {rejected.map((q) => (
                  <li key={q.id} className="sticker-flat bg-tomato-soft px-3 py-2 text-sm font-semibold">
                    {q.prompt}
                    <span className="block text-ink-soft">claimed quote: “{q.evidence}”</span>
                  </li>
                ))}
              </ul>
            </details>
          )}
        </>
      )}

      {tab === "simple" && (
        <>
          <p className="alert alert-info mt-5">
            The simple version is for students who find the technical words hard. Check that the analogy matches your notes: a
            misleading analogy is worse than none. Fix the wording here, or reject it.
          </p>
          {explanations && explanations.length === 0 && <AllCaughtUp what="simple explanations" />}
          <div className="mt-6 grid gap-5 xl:grid-cols-2">
            {explanations?.map((e) =>
              me ? (
                <ExplanationCard key={e.topic_id} item={e} onDone={explanationDone} onError={setError} />
              ) : null,
            )}
          </div>
        </>
      )}
    </FacultyShell>
  );
}

function AllCaughtUp({ what }: { what: string }) {
  return (
    <div className="sticker-lg mt-6 flex flex-col items-center gap-2 bg-mint-soft p-8 text-center">
      <Snappy pose="celebrate" size={130} />
      <p className="font-display text-2xl font-extrabold">All caught up!</p>
      <p className="font-semibold text-ink-soft">No {what} waiting for review.</p>
    </div>
  );
}

function ExplanationCard({
  item,
  onDone,
  onError,
}: {
  item: Explanation;
  onDone: (topicId: number) => void;
  onError: (message: string) => void;
}) {
  const [text, setText] = useState(item.simple_explanation);
  const [analogy, setAnalogy] = useState(item.analogy);
  const [glossary, setGlossary] = useState<GlossaryTerm[]>(item.glossary);
  const [busy, setBusy] = useState(false);

  async function decide(status: "approved" | "rejected") {
    setBusy(true);
    try {
      await api.reviewExplanation(item.topic_id, status === "approved"
        ? { status, simple_explanation: text, analogy, glossary }
        : { status });
      onDone(item.topic_id);
    } catch (e) {
      onError((e as Error).message);
      setBusy(false);
    }
  }

  return (
    <article className="sticker-lg flex flex-col p-5">
      <span className="chip self-start bg-sky-soft">Topic {item.position}</span>
      <h2 className="mt-2 font-display text-xl font-extrabold leading-snug">{item.title}</h2>
      {item.summary && (
        <details className="mt-1">
          <summary className="cursor-pointer text-sm font-bold text-ink-soft">Full summary, for comparison</summary>
          <p className="mt-1 text-sm font-semibold text-ink-soft">{item.summary}</p>
        </details>
      )}
      <label className="mt-3 text-sm font-bold">
        Simple explanation
        <textarea rows={4} value={text} onChange={(e) => setText(e.target.value)} className="input mt-1" />
      </label>
      <label className="mt-3 text-sm font-bold">
        💡 Analogy
        <textarea rows={2} value={analogy} onChange={(e) => setAnalogy(e.target.value)} className="input mt-1" />
      </label>
      {glossary.length > 0 && (
        <div className="mt-3">
          <p className="text-sm font-bold">Words to know</p>
          <ul className="mt-1 space-y-1.5">
            {glossary.map((g) => (
              <li key={g.term} className="sticker-flat flex items-start justify-between gap-2 px-3 py-1.5 text-sm font-semibold">
                <span><b>{g.term}</b>: {g.meaning}</span>
                <button
                  onClick={() => setGlossary((list) => list.filter((x) => x.term !== g.term))}
                  aria-label={`Remove ${g.term}`}
                  className="font-extrabold text-tomato"
                >
                  ✕
                </button>
              </li>
            ))}
          </ul>
        </div>
      )}
      <div className="mt-4 flex gap-2">
        <button disabled={busy} onClick={() => decide("approved")} className="btn btn-mint flex-1">Approve</button>
        <button disabled={busy} onClick={() => decide("rejected")} className="btn btn-white flex-1">Reject</button>
      </div>
    </article>
  );
}
