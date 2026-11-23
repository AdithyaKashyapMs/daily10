"use client";

import Link from "next/link";
import { useParams } from "next/navigation";
import { useEffect, useState } from "react";
import { api, type TopicRow } from "@/lib/api";
import { useFaculty } from "@/lib/session";
import FacultyShell from "@/components/FacultyShell";
import Snappy from "@/components/Snappy";

export default function SubjectTopics() {
  useFaculty();
  const { code } = useParams<{ code: string }>();
  const [topics, setTopics] = useState<TopicRow[] | null>(null);
  const [error, setError] = useState("");

  useEffect(() => {
    api.topics(code).then(setTopics).catch((e) => setError((e as Error).message));
  }, [code]);

  const n = (t: TopicRow, k: keyof TopicRow["questions"]) => t.questions[k] ?? 0;
  const totals = topics?.reduce(
    (a, t) => ({ approved: a.approved + n(t, "approved"), draft: a.draft + n(t, "draft") }),
    { approved: 0, draft: 0 },
  );
  const maxWeight = Math.max(1, ...(topics ?? []).map((t) => t.exam_weight));

  return (
    <FacultyShell subject={code}>
      <h1 className="font-display text-4xl font-extrabold">{code} · Topics</h1>
      <p className="mt-1 font-semibold text-ink-soft">Daily topics in syllabus order, and how often each was asked in past papers.</p>
      {error && <p className="alert alert-error mt-4">{error}</p>}

      {topics && topics.length === 0 && (
        <div className="sticker-lg mt-6 flex flex-col items-center gap-3 bg-sun-soft p-8 text-center">
          <Snappy pose="papers" size={130} />
          <p className="font-display text-2xl font-extrabold">No notes yet</p>
          <Link href={`/faculty/${code}/upload`} className="btn btn-primary">Upload notes</Link>
        </div>
      )}

      {topics && topics.length > 0 && totals && (
        <>
          <div className="mt-6 grid gap-4 sm:grid-cols-3">
            {[
              { label: "Daily topics", value: topics.length, tint: "bg-sky-soft" },
              { label: "Questions approved", value: totals.approved, tint: "bg-mint-soft" },
              { label: "Waiting for review", value: totals.draft, tint: "bg-sun-soft", href: `/faculty/${code}/review` },
            ].map((s) => (
              <div key={s.label} className={`sticker p-4 ${s.tint}`}>
                <p className="font-bold text-ink-soft">{s.label}</p>
                <p className="font-display text-4xl font-extrabold tabular-nums">{s.value}</p>
                {s.href && s.value > 0 && <Link href={s.href} className="text-sm font-extrabold text-tomato underline">Review now →</Link>}
              </div>
            ))}
          </div>

          <div className="sticker mt-6 overflow-x-auto">
            <table className="w-full min-w-[640px] text-left">
              <thead className="border-b-[2.5px] border-ink bg-sun-soft font-display text-lg">
                <tr>
                  <th className="px-4 py-2.5">#</th>
                  <th className="px-4 py-2.5">Topic</th>
                  <th className="px-4 py-2.5">Asked in exams</th>
                  <th className="px-4 py-2.5">Questions</th>
                </tr>
              </thead>
              <tbody>
                {topics.map((t) => (
                  <tr key={t.id} className="border-b-2 border-ink/10 font-semibold last:border-0">
                    <td className="px-4 py-2.5 tabular-nums text-ink-soft">{t.position}</td>
                    <td className="px-4 py-2.5">
                      {t.title}
                      {t.title !== t.source && <span className="block text-xs text-ink-soft">{t.source}</span>}
                    </td>
                    <td className="px-4 py-2.5">
                      <div className="flex items-center gap-2">
                        <div className="meter w-24"><span style={{ width: `${(t.exam_weight / maxWeight) * 100}%`, background: "var(--tomato)" }} /></div>
                        <span className="tabular-nums">{t.exam_weight}×</span>
                      </div>
                    </td>
                    <td className="space-x-1 px-4 py-2.5">
                      {n(t, "approved") > 0 && <span className="chip bg-mint-soft">{n(t, "approved")} approved</span>}
                      {n(t, "draft") > 0 && <span className="chip bg-sun-soft">{n(t, "draft")} to review</span>}
                      {n(t, "auto_rejected") > 0 && <span className="chip bg-tomato-soft">{n(t, "auto_rejected")} auto-rejected</span>}
                      {!Object.keys(t.questions).length && <span className="text-sm text-ink-soft">not generated</span>}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </>
      )}
    </FacultyShell>
  );
}
