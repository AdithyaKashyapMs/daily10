"use client";

import Link from "next/link";
import { useCallback, useEffect, useState } from "react";
import { api, type Subject } from "@/lib/api";
import { useFaculty } from "@/lib/session";
import FacultyShell from "@/components/FacultyShell";
import Snappy from "@/components/Snappy";

const BLOCKS = ["block-sky", "block-tomato", "block-mint", "block-plum", "block-sun"];

export default function FacultyHome() {
  const me = useFaculty();
  const [subjects, setSubjects] = useState<Subject[] | null>(null);
  const [form, setForm] = useState({ code: "", name: "", department: "", semester: 5 });
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);

  const load = useCallback(async () => {
    try {
      setSubjects(await api.subjects());
    } catch (e) {
      setError((e as Error).message);
    }
  }, []);

  useEffect(() => {
    load();
  }, [load]);
  useEffect(() => {
    if (me) setForm((f) => ({ ...f, department: f.department || me.department }));
  }, [me]);

  async function create(e: React.FormEvent) {
    e.preventDefault();
    if (!me) return;
    setBusy(true);
    setError("");
    try {
      await api.createSubject(form);
      setForm({ ...form, code: "", name: "" });
      await load();
    } catch (err) {
      setError((err as Error).message);
    } finally {
      setBusy(false);
    }
  }

  return (
    <FacultyShell>
      <h1 className="font-display text-4xl font-extrabold">Hi, {me?.name.split(" ").slice(0, 2).join(" ") ?? "…"}</h1>
      <p className="mt-1 font-semibold text-ink-soft">Your subjects. Upload notes, approve questions, and every enrolled student gets a daily plan.</p>
      {error && <p className="alert alert-error mt-4">{error}</p>}

      <div className="mt-6 grid gap-6 sm:grid-cols-2 xl:grid-cols-3">
        {subjects?.map((s, i) => (
          <Link key={s.code} href={`/faculty/${s.code}`} className="sticker-lg block overflow-hidden transition hover:-translate-x-0.5 hover:-translate-y-0.5">
            <div className={`${BLOCKS[i % BLOCKS.length]} flex items-end justify-between border-b-[3px] border-ink px-5 pt-4`}>
              <span className="chip mb-4 bg-white text-ink">{s.code}</span>
              <Snappy pose={i % 2 ? "pencil" : "book"} size={80} bob={false} />
            </div>
            <div className="p-5">
              <h2 className="font-display text-2xl font-extrabold leading-tight">{s.name}</h2>
              <p className="mt-1 font-semibold text-ink-soft">
                {s.department || "—"} · Sem {s.semester || "—"} · {s.topics} topic{s.topics === 1 ? "" : "s"}
              </p>
            </div>
          </Link>
        ))}

        <form onSubmit={create} className="sticker-lg flex flex-col gap-3 border-dashed bg-sun-soft p-5">
          <h2 className="font-display text-2xl font-extrabold">➕ New subject</h2>
          <div className="grid grid-cols-[7rem_1fr] gap-3">
            <div>
              <label htmlFor="n-code" className="label">Code</label>
              <input id="n-code" value={form.code} onChange={(e) => setForm({ ...form, code: e.target.value })} required className="input" placeholder="21CS53" />
            </div>
            <div>
              <label htmlFor="n-sem" className="label">Semester</label>
              <input id="n-sem" type="number" min={1} max={8} value={form.semester} onChange={(e) => setForm({ ...form, semester: Number(e.target.value) })} className="input" />
            </div>
          </div>
          <div>
            <label htmlFor="n-name" className="label">Name</label>
            <input id="n-name" value={form.name} onChange={(e) => setForm({ ...form, name: e.target.value })} required className="input" placeholder="Database Management Systems" />
          </div>
          <div>
            <label htmlFor="n-dept" className="label">Department</label>
            <input id="n-dept" value={form.department} onChange={(e) => setForm({ ...form, department: e.target.value })} className="input" />
          </div>
          <button type="submit" disabled={busy || !me} className="btn btn-primary">{busy ? "Creating…" : "Create subject"}</button>
        </form>
      </div>
    </FacultyShell>
  );
}
