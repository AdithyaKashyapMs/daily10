"use client";

import { Suspense, useCallback, useEffect, useState } from "react";
import { useRouter, useSearchParams } from "next/navigation";
import { api, type Profile, type Subject } from "@/lib/api";
import { clearCode, useStudentCode } from "@/lib/session";
import { Loading, StudentFrame } from "@/components/BottomNav";

const BOT = process.env.NEXT_PUBLIC_TELEGRAM_BOT ?? "";

function inDays(n: number) {
  const d = new Date();
  d.setDate(d.getDate() + n);
  return d.toISOString().slice(0, 10);
}

function SettingsInner() {
  const code = useStudentCode();
  const router = useRouter();
  const welcome = useSearchParams()?.get("welcome") === "1";
  const [profile, setProfile] = useState<Profile | null>(null);
  const [subjects, setSubjects] = useState<Subject[]>([]);
  const [pick, setPick] = useState("");
  const [exam, setExam] = useState(inDays(90));
  const [time, setTime] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [saved, setSaved] = useState<string | null>(null);
  const [copied, setCopied] = useState(false);

  const load = useCallback(async () => {
    if (!code) return;
    try {
      const [p, s] = await Promise.all([api.profile(code), api.subjects()]);
      setProfile(p);
      setTime(p.notify_time);
      setSubjects(s);
      const available = s.filter((x) => !p.subjects.some((e) => e.code === x.code));
      setPick(available[0]?.code ?? "");
    } catch (e) {
      setError((e as Error).message);
    }
  }, [code]);

  useEffect(() => {
    load();
  }, [load]);

  async function addSubject() {
    if (!code || !pick) return;
    try {
      await api.enroll(code, pick, exam);
      setSaved("Subject added. Your plan starts today.");
      await load();
    } catch (e) {
      setError((e as Error).message);
    }
  }

  async function saveTime() {
    if (!code) return;
    try {
      await api.updateReminder(code, time);
      setSaved(`Reminder set for ${time} every day.`);
    } catch (e) {
      setError((e as Error).message);
    }
  }

  async function copyCode() {
    if (!code) return;
    try {
      await navigator.clipboard.writeText(code);
      setCopied(true);
      setTimeout(() => setCopied(false), 1500);
    } catch {}
  }

  if (!profile) return error ? <p className="alert alert-error">{error}</p> : <Loading label="Loading…" />;
  const available = subjects.filter((x) => !profile.subjects.some((e) => e.code === x.code));

  return (
    <>
      {welcome && (
        <div className="sticker bg-mint-soft p-4">
          <p className="font-display text-xl font-extrabold">Welcome, {profile.name.split(" ")[0]}! 👋</p>
          <p className="mt-1 font-semibold">Your code is <b className="font-mono tracking-widest">{profile.code}</b>. Keep it to log in on another phone.</p>
          <p className="mt-1 font-semibold">Next: add your subjects and exam dates below.</p>
        </div>
      )}
      {saved && <p className="alert alert-ok" role="status">{saved}</p>}
      {error && <p className="alert alert-error">{error}</p>}

      <section className="sticker flex flex-col gap-3 p-5">
        <h2 className="font-display text-2xl font-extrabold">My subjects</h2>
        {profile.subjects.length === 0 && <p className="font-semibold text-ink-soft">None yet.</p>}
        {profile.subjects.map((s) => (
          <div key={s.code} className="sticker-flat flex items-baseline justify-between gap-3 bg-sky-soft px-3 py-2 font-bold">
            <span>{s.name}</span>
            <span className="shrink-0 text-xs text-ink-soft">exam {new Date(s.exam_date + "T00:00:00").toLocaleDateString(undefined, { day: "numeric", month: "short" })}</span>
          </div>
        ))}
        {available.length > 0 ? (
          <div className="flex flex-col gap-2 pt-1">
            <label htmlFor="subject" className="label">Add a subject</label>
            <select id="subject" value={pick} onChange={(e) => setPick(e.target.value)} className="input">
              {available.map((s) => (
                <option key={s.code} value={s.code}>{s.code} · {s.name}</option>
              ))}
            </select>
            <label htmlFor="exam" className="label">Exam date</label>
            <input id="exam" type="date" min={inDays(1)} value={exam} onChange={(e) => setExam(e.target.value)} className="input" />
            <button onClick={addSubject} disabled={!pick} className="btn btn-primary btn-block">Add subject</button>
          </div>
        ) : (
          <p className="font-semibold text-ink-soft">{subjects.length ? "You've added every available subject." : "No subjects yet: your faculty adds them."}</p>
        )}
      </section>

      <section className="sticker flex flex-col gap-3 bg-sun-soft p-5">
        <h2 className="font-display text-2xl font-extrabold">Daily reminder</h2>
        <div className="flex gap-2">
          <input type="time" aria-label="Reminder time" value={time} onChange={(e) => setTime(e.target.value)} className="input flex-1" />
          <button onClick={saveTime} disabled={time === profile.notify_time} className="btn btn-white">Save</button>
        </div>
        <p className="font-semibold text-ink-soft">
          {profile.telegram_linked
            ? "✅ Telegram reminders are on."
            : BOT
              ? <>Get reminders on Telegram: open <a className="font-extrabold text-tomato underline" href={`https://t.me/${BOT}?start=${profile.code}`}>@{BOT}</a> and tap Start.</>
              : "Telegram reminders will appear here once your college sets up the bot."}
        </p>
      </section>

      <section className="sticker flex items-center justify-between gap-3 p-5">
        <div>
          <p className="font-bold text-ink-soft">Your login code</p>
          <p className="font-mono text-2xl font-bold tracking-[0.3em]">{profile.code}</p>
        </div>
        <button onClick={copyCode} className="btn btn-sun btn-sm">{copied ? "Copied!" : "Copy"}</button>
      </section>

      <button onClick={() => { clearCode(); router.replace("/"); }} className="btn btn-white btn-block">Log out</button>
    </>
  );
}

export default function Settings() {
  return (
    <StudentFrame>
      <h1 className="font-display text-4xl font-extrabold">Me</h1>
      <Suspense fallback={<Loading label="Loading…" />}>
        <SettingsInner />
      </Suspense>
    </StudentFrame>
  );
}
