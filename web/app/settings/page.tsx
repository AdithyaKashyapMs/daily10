"use client";

import { Suspense, useCallback, useEffect, useState } from "react";
import { useRouter, useSearchParams } from "next/navigation";
import { api, type Profile, type Subject } from "@/lib/api";
import { clearStudent, useStudent } from "@/lib/session";
import { Loading, StudentFrame } from "@/components/BottomNav";
import PasswordInput from "@/components/PasswordInput";

const BOT = (process.env.NEXT_PUBLIC_TELEGRAM_BOT ?? "").replace(/^@/, "");

function inDays(n: number) {
  const d = new Date();
  d.setDate(d.getDate() + n);
  return d.toISOString().slice(0, 10);
}

function SettingsInner() {
  const ready = useStudent();
  const router = useRouter();
  const welcome = useSearchParams()?.get("welcome") === "1";
  const [profile, setProfile] = useState<Profile | null>(null);
  const [subjects, setSubjects] = useState<Subject[]>([]);
  const [pick, setPick] = useState("");
  const [exam, setExam] = useState(inDays(90));
  const [time, setTime] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [saved, setSaved] = useState<string | null>(null);
  const [linking, setLinking] = useState(false);
  const [pw, setPw] = useState({ open: false, current: "", next: "", busy: false });

  const load = useCallback(async () => {
    if (!ready) return;
    try {
      const [p, s] = await Promise.all([api.profile(), api.subjects()]);
      setProfile(p);
      setTime(p.notify_time);
      setSubjects(s);
      const available = s.filter((x) => !p.subjects.some((e) => e.code === x.code));
      setPick(available[0]?.code ?? "");
    } catch (e) {
      setError((e as Error).message);
    }
  }, [ready]);

  useEffect(() => {
    load();
  }, [load]);

  async function addSubject() {
    if (!pick) return;
    try {
      await api.enroll(pick, exam);
      setSaved("Subject added. Your plan starts today.");
      await load();
    } catch (e) {
      setError((e as Error).message);
    }
  }

  async function saveTime() {
    try {
      await api.updateReminder(time);
      setSaved(`Reminder set for ${time} every day.`);
    } catch (e) {
      setError((e as Error).message);
    }
  }

  async function linkTelegram() {
    // Open the tab first (in the click), then point it at the bot: phones block pop-ups opened later.
    const tab = window.open("", "_blank");
    setLinking(true);
    try {
      const link = await api.telegramLink();
      const url = link.url ?? `https://t.me/${BOT}?start=${link.code}`;
      if (tab) tab.location.href = url;
      else window.location.href = url;
      setSaved("In Telegram, tap Start. Then come back here.");
    } catch (e) {
      tab?.close();
      setError((e as Error).message);
    } finally {
      setLinking(false);
    }
  }

  async function changePassword(e: React.FormEvent) {
    e.preventDefault();
    setError(null);
    setPw((p) => ({ ...p, busy: true }));
    try {
      await api.changePassword(pw.current, pw.next);
      setPw({ open: false, current: "", next: "", busy: false });
      setSaved("Password changed.");
    } catch (err) {
      setError((err as Error).message);
      setPw((p) => ({ ...p, busy: false }));
    }
  }

  async function logOut(everywhere: boolean) {
    await api.studentLogout(everywhere).catch(() => {});
    clearStudent();
    router.replace("/");
  }

  if (!profile) return error ? <p className="alert alert-error">{error}</p> : <Loading label="Loading…" />;
  const available = subjects.filter((x) => !profile.subjects.some((e) => e.code === x.code));

  return (
    <>
      {welcome && (
        <div className="sticker bg-mint-soft p-4">
          <p className="font-display text-xl font-extrabold">Welcome, {profile.name.split(" ")[0]}! 👋</p>
          <p className="mt-1 font-semibold">On another phone, just log in with {profile.email ?? "your college email"} again.</p>
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
              ? "Get your daily reminder as a Telegram message."
              : "Telegram reminders will appear here once your college sets up the bot."}
        </p>
        {!profile.telegram_linked && BOT && (
          <button onClick={linkTelegram} disabled={linking} className="btn btn-white btn-block">
            {linking ? "Opening Telegram…" : "Turn on Telegram reminders"}
          </button>
        )}
      </section>

      <section className="sticker flex flex-col gap-3 p-5">
        <div>
          <p className="font-bold text-ink-soft">Signed in as</p>
          <p className="font-bold">{profile.email ?? profile.name}</p>
        </div>
        {pw.open ? (
          <form onSubmit={changePassword} className="space-y-3">
            <div>
              <label htmlFor="pw-current" className="label">Current password</label>
              <PasswordInput id="pw-current" value={pw.current} onChange={(v) => setPw((p) => ({ ...p, current: v }))} autoComplete="current-password" />
            </div>
            <div>
              <label htmlFor="pw-next" className="label">New password</label>
              <PasswordInput id="pw-next" value={pw.next} onChange={(v) => setPw((p) => ({ ...p, next: v }))} autoComplete="new-password" minLength={8} />
              <p className="hint">At least 8 characters.</p>
            </div>
            <div className="flex gap-2">
              <button type="submit" disabled={pw.busy || !pw.current || pw.next.length < 8} className="btn btn-primary flex-1">
                {pw.busy ? "Saving…" : "Save password"}
              </button>
              <button type="button" onClick={() => setPw({ open: false, current: "", next: "", busy: false })} className="btn btn-white">Cancel</button>
            </div>
          </form>
        ) : (
          <button onClick={() => setPw((p) => ({ ...p, open: true }))} className="btn btn-white btn-block">Change password</button>
        )}
        <button onClick={() => logOut(false)} className="btn btn-white btn-block">Log out</button>
        <button onClick={() => logOut(true)} className="text-sm font-bold text-ink-soft underline">Log out on all my devices</button>
      </section>
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
