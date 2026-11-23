"use client";

import { useParams } from "next/navigation";
import { useCallback, useEffect, useState } from "react";
import { api, type ReviewQuestion } from "@/lib/api";
import { useFaculty } from "@/lib/session";
import FacultyShell from "@/components/FacultyShell";
import Snappy from "@/components/Snappy";

const LETTERS = ["A", "B", "C", "D"];

export default function ReviewPage() {
  const me = useFaculty();
  const { code } = useParams<{ code: string }>();
  const [drafts, setDrafts] = useState<ReviewQuestion[] | null>(null);
  const [rejected, setRejected] = useState<ReviewQuestion[]>([]);
  const [error, setError] = useState("");
  const [done, setDone] = useState(0);

  const load = useCallback(async () => {
    if (!me) return;
    try {
      const [d, r] = await Promise.all([api.questions(me.token, code, "draft"), api.questions(me.token, code, "auto_rejected")]);
      setDrafts(d);
      setRejected(r);
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
      await api.setStatus(me.token, q.id, status);
      setDrafts((d) => d?.filter((x) => x.id !== q.id) ?? null);
      setDone((n) => n + 1);
    } catch (e) {
      setError((e as Error).message);
    }
  }

  return (
    <FacultyShell subject={code}>
      <h1 className="font-display text-4xl font-extrabold">Review questions</h1>
      <p className="mt-1 font-semibold text-ink-soft">Students only ever see questions you approve. Questions an independent AI check flagged, or students reported, are shown first.</p>
      {error && <p className="alert alert-error mt-4">{error}</p>}
      {done > 0 && <p className="alert alert-ok mt-4">{done} reviewed this session.</p>}

      {drafts && drafts.length === 0 && (
        <div className="sticker-lg mt-6 flex flex-col items-center gap-2 bg-mint-soft p-8 text-center">
          <Snappy pose="celebrate" size={130} />
          <p className="font-display text-2xl font-extrabold">All caught up!</p>
          <p className="font-semibold text-ink-soft">No questions waiting for review.</p>
        </div>
      )}

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
    </FacultyShell>
  );
}
