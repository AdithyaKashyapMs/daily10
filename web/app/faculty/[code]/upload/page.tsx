"use client";

import { useParams } from "next/navigation";
import { useState } from "react";
import { api, type GenerateStats } from "@/lib/api";
import { useFaculty } from "@/lib/session";
import FacultyShell from "@/components/FacultyShell";
import Snappy from "@/components/Snappy";

const NOTE_TYPES = ".pdf,.docx,.pptx,.txt,.html";

function DropZone({ label, hint, multiple, onFiles, tint }: { label: string; hint: string; multiple: boolean; onFiles: (f: File[]) => void; tint: string }) {
  const [dragging, setDragging] = useState(false);
  return (
    <label
      onDragOver={(e) => { e.preventDefault(); setDragging(true); }}
      onDragLeave={() => setDragging(false)}
      onDrop={(e) => { e.preventDefault(); setDragging(false); onFiles(Array.from(e.dataTransfer.files)); }}
      className={`sticker-lg flex cursor-pointer flex-col items-center gap-2 border-dashed p-6 text-center transition-colors ${dragging ? "bg-sky-soft" : tint}`}
    >
      <Snappy pose="papers" size={100} bob={false} />
      <span className="font-display text-xl font-extrabold">{label}</span>
      <span className="text-sm font-semibold text-ink-soft">{hint}</span>
      <input type="file" accept={NOTE_TYPES} multiple={multiple} className="sr-only" onChange={(e) => onFiles(Array.from(e.target.files ?? []))} />
    </label>
  );
}

export default function UploadPage() {
  const me = useFaculty();
  const { code } = useParams<{ code: string }>();
  const [notes, setNotes] = useState<File[]>([]);
  const [paper, setPaper] = useState<File | null>(null);
  const [year, setYear] = useState("");
  const [limit, setLimit] = useState(5);
  const [busy, setBusy] = useState<"" | "notes" | "paper" | "generate">("");
  const [msg, setMsg] = useState<{ kind: "ok" | "error"; text: string } | null>(null);
  const [stats, setStats] = useState<GenerateStats | null>(null);

  async function run(kind: "notes" | "paper" | "generate", fn: () => Promise<string>) {
    setBusy(kind);
    setMsg(null);
    try {
      setMsg({ kind: "ok", text: await fn() });
    } catch (e) {
      setMsg({ kind: "error", text: (e as Error).message });
    } finally {
      setBusy("");
    }
  }

  return (
    <FacultyShell subject={code}>
      <h1 className="font-display text-4xl font-extrabold">Upload & generate</h1>
      <p className="mt-1 font-semibold text-ink-soft">Notes become daily topics. Past papers tell students which topics are asked most.</p>
      {msg && <p className={`alert mt-4 ${msg.kind === "ok" ? "alert-ok" : "alert-error"}`} role="status">{msg.text}</p>}

      <div className="mt-6 grid gap-6 lg:grid-cols-2">
        <section className="flex flex-col gap-3">
          <h2 className="font-display text-2xl font-extrabold">1 · Lecture notes</h2>
          <DropZone label="Drop notes here" hint="PDF, Word, PowerPoint or text · in syllabus order" multiple tint="bg-sun-soft" onFiles={(f) => setNotes((prev) => [...prev, ...f])} />
          {notes.length > 0 && (
            <ul className="space-y-1.5">
              {notes.map((f, i) => (
                <li key={i} className="sticker-flat flex items-center justify-between gap-2 px-3 py-1.5 text-sm font-bold">
                  <span className="truncate">📄 {f.name}</span>
                  <button onClick={() => setNotes(notes.filter((_, j) => j !== i))} aria-label={`Remove ${f.name}`} className="font-extrabold text-tomato">✕</button>
                </li>
              ))}
            </ul>
          )}
          <button
            disabled={!me || !notes.length || !!busy}
            onClick={() => run("notes", async () => {
              const r = await api.uploadNotes(code, notes);
              setNotes([]);
              return `Added ${r.topics_added} daily topics.`;
            })}
            className="btn btn-primary"
          >
            {busy === "notes" ? "Reading notes…" : `Add ${notes.length || ""} file${notes.length === 1 ? "" : "s"}`}
          </button>
        </section>

        <section className="flex flex-col gap-3">
          <h2 className="font-display text-2xl font-extrabold">2 · Past exam papers</h2>
          <DropZone label={paper ? `📄 ${paper.name}` : "Drop one paper here"} hint="Selectable-text PDFs work best · year read from the file name" multiple={false} tint="bg-plum-soft" onFiles={(f) => setPaper(f[0] ?? null)} />
          <div>
            <label htmlFor="p-year" className="label">Year (optional)</label>
            <input id="p-year" inputMode="numeric" value={year} onChange={(e) => setYear(e.target.value.replace(/\D/g, "").slice(0, 4))} className="input" placeholder="2024" />
          </div>
          <button
            disabled={!me || !paper || !!busy}
            onClick={() => run("paper", async () => {
              const r = await api.uploadPaper(code, paper!, year ? Number(year) : undefined);
              setPaper(null);
              return `Found ${r.questions_found} questions and matched them to topics.`;
            })}
            className="btn btn-sky"
          >
            {busy === "paper" ? "Matching questions…" : "Add past paper"}
          </button>
        </section>
      </div>

      <section className="sticker-lg mt-8 overflow-hidden">
        <div className="block-mint flex items-end gap-3 border-b-[3px] border-ink px-5 pt-3">
          <Snappy pose="pencil" size={80} bob={false} />
          <h2 className="pb-4 font-display text-2xl font-extrabold">3 · Generate summaries & questions</h2>
        </div>
        <div className="flex flex-col gap-3 p-5">
          <p className="font-semibold text-ink-soft">
            For each topic, the AI writes a short summary, key points and 6 questions. Each question must quote your notes, or it is rejected
            automatically. Nothing reaches students until you approve it.
          </p>
          <div className="flex flex-wrap items-end gap-3">
            <div className="w-40">
              <label htmlFor="g-limit" className="label">Topics this batch</label>
              <input id="g-limit" type="number" min={1} max={50} value={limit} onChange={(e) => setLimit(Number(e.target.value))} className="input" />
            </div>
            <button
              disabled={!me || !!busy}
              onClick={() => run("generate", async () => {
                const s = await api.generate(code, limit);
                setStats(s);
                return s.topics ? `Done: ${s.topics} topics, ${s.draft} questions ready for review.` : "Every topic already has questions.";
              })}
              className="btn btn-mint"
            >
              {busy === "generate" ? "Generating… (about 20 s per topic)" : "✨ Generate"}
            </button>
          </div>
          <button
            disabled={!me || !!busy}
            onClick={() => run("generate", async () => {
              const c = await api.check(code);
              return c.checked ? `AI check: ${c.passed} passed, ${c.flagged} flagged for a closer look${c.errors ? `, ${c.errors} couldn't be checked` : ""}.` : "No unchecked drafts.";
            })}
            className="btn btn-white self-start"
          >
            🔎 Run AI check on drafts
          </button>
          <p className="hint">A different AI model answers each question blind, from your notes only, and flags ones that look wrong or ambiguous.</p>
          {stats && (
            <div className="flex flex-wrap gap-2">
              <span className="chip bg-sun-soft">{stats.draft} to review</span>
              <span className="chip bg-tomato-soft">{stats.auto_rejected} auto-rejected</span>
              {stats.simple_explanations > 0 && (
                <span className="chip bg-sky-soft">{stats.simple_explanations} simple explanations to review</span>
              )}
              {stats.levels_tagged > 0 && (
                <span className="chip bg-mint-soft">{stats.levels_tagged} questions tagged warm-up / core / exam</span>
              )}
              {stats.failed_topics > 0 && <span className="chip bg-tomato-soft">{stats.failed_topics} topics failed (try again)</span>}
            </div>
          )}
          <p className="hint">Free AI tiers have daily limits, so generate in batches of about 5.</p>
        </div>
      </section>
    </FacultyShell>
  );
}
