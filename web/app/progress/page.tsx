"use client";

import { useCallback, useEffect, useState } from "react";
import { api, type Progress } from "@/lib/api";
import { useStudent } from "@/lib/session";
import { Loading, StudentFrame } from "@/components/BottomNav";
import Snappy from "@/components/Snappy";

export default function ProgressPage() {
  const ready = useStudent();
  const [data, setData] = useState<Progress | null>(null);
  const [error, setError] = useState("");

  const load = useCallback(async () => {
    if (!ready) return;
    setError("");
    try {
      setData(await api.progress());
    } catch (e) {
      setError((e as Error).message);
    }
  }, [ready]);

  useEffect(() => {
    load();
  }, [load]);

  return (
    <StudentFrame>
      <header>
        <p className="font-bold text-ink-soft">{data?.student ?? ""}</p>
        <h1 className="font-display text-4xl font-extrabold">Progress</h1>
      </header>
      {error && <p className="alert alert-error">{error}</p>}
      {!data && !error && <Loading label="Counting your streak…" />}
      {data && (
        <>
          <div className="sticker-lg block-sun flex items-center gap-4 overflow-hidden px-5 py-4">
            <Snappy pose="fire" size={96} />
            <div>
              <p className="font-display text-6xl font-extrabold leading-none tabular-nums">{data.streak_days}</p>
              <p className="font-display text-xl font-bold">day streak</p>
              <p className="text-sm font-bold text-ink/70">
                {data.accuracy === null ? "No answers yet" : `${Math.round(data.accuracy * 100)}% right · ${data.answers} answer${data.answers === 1 ? "" : "s"}`}
              </p>
            </div>
          </div>

          <section className="sticker p-5">
            <h2 className="font-display text-2xl font-extrabold">Syllabus covered</h2>
            {data.subjects.length === 0 && <p className="mt-2 font-semibold text-ink-soft">No subjects yet.</p>}
            <div className="mt-3 space-y-4">
              {data.subjects.map((s) => (
                <div key={s.code}>
                  <div className="flex items-baseline justify-between gap-2 font-bold">
                    <span>{s.subject}</span>
                    <span className="shrink-0 tabular-nums">{s.covered}/{s.topics}</span>
                  </div>
                  <div className="meter mt-1.5" role="progressbar" aria-valuenow={Math.round(s.coverage * 100)} aria-valuemin={0} aria-valuemax={100}>
                    <span style={{ width: `${Math.max(s.coverage * 100, 3)}%` }} />
                  </div>
                  <p className="mt-1 text-sm font-semibold text-ink-soft">
                    {s.days_to_exam >= 0 ? `Exam in ${s.days_to_exam} day${s.days_to_exam === 1 ? "" : "s"}` : "Exam done"} ·{" "}
                    {new Date(s.exam_date + "T00:00:00").toLocaleDateString(undefined, { day: "numeric", month: "short" })}
                  </p>
                </div>
              ))}
            </div>
          </section>

          <section className="sticker bg-tomato-soft p-5">
            <h2 className="font-display text-2xl font-extrabold">Needs practice</h2>
            {data.weak_topics.length === 0 ? (
              <p className="mt-2 font-semibold text-ink-soft">Nothing yet. Topics you miss show up here and come back in your reviews.</p>
            ) : (
              <ul className="mt-3 space-y-2">
                {data.weak_topics.map((w) => (
                  <li key={w.topic} className="sticker-flat flex items-center justify-between gap-3 px-3 py-2 font-bold">
                    <span>{w.topic}</span>
                    <span className="chip shrink-0 bg-white">{w.misses} missed</span>
                  </li>
                ))}
              </ul>
            )}
          </section>
        </>
      )}
    </StudentFrame>
  );
}
