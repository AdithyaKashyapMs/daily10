"use client";

import { useState } from "react";
import { useRouter } from "next/navigation";
import Link from "next/link";
import { api, ApiError } from "@/lib/api";
import { setCode } from "@/lib/session";
import AuthShell from "@/components/AuthShell";

export default function StudentLogin() {
  const router = useRouter();
  const [mode, setMode] = useState<"new" | "code">("new");
  const [name, setName] = useState("");
  const [time, setTime] = useState("19:00");
  const [code, setCodeInput] = useState("");
  const [error, setError] = useState("");
  const [loading, setLoading] = useState(false);

  async function createAccount(e: React.FormEvent) {
    e.preventDefault();
    setError("");
    setLoading(true);
    try {
      const res = await api.register(name.trim(), time);
      setCode(res.code);
      router.replace("/settings?welcome=1");
    } catch (err) {
      setError(err instanceof Error ? err.message : "Couldn't create your account.");
    } finally {
      setLoading(false);
    }
  }

  async function signIn(e: React.FormEvent) {
    e.preventDefault();
    setError("");
    setLoading(true);
    try {
      await api.profile(code.trim().toUpperCase());
      setCode(code.trim());
      router.replace("/today");
    } catch (err) {
      setError(err instanceof ApiError && err.status === 404 ? "No student with that code." : (err as Error).message);
    } finally {
      setLoading(false);
    }
  }

  return (
    <AuthShell
      block="block-sun"
      pose="book"
      bubble={mode === "new" ? "Ten minutes a day. Deal?" : "Hey, welcome back!"}
      tagline="Your syllabus, a little every day. No panic in exam week."
      title={mode === "new" ? "Student sign up" : "Student login"}
      subtitle="For students: your daily 10 minutes."
    >
      <div className="mb-5 flex gap-2" role="tablist">
        <button role="tab" aria-selected={mode === "new"} onClick={() => setMode("new")} className="tab">I&apos;m new</button>
        <button role="tab" aria-selected={mode === "code"} onClick={() => setMode("code")} className="tab">I have a code</button>
      </div>
      {error && <p className="alert alert-error mb-4" role="alert">{error}</p>}

      {mode === "new" ? (
        <form onSubmit={createAccount} className="space-y-4">
          <div>
            <label htmlFor="s-name" className="label">Your name</label>
            <input id="s-name" value={name} onChange={(e) => setName(e.target.value)} required maxLength={120} autoComplete="name" className="input" placeholder="Asha Rao" />
          </div>
          <div>
            <label htmlFor="s-time" className="label">Remind me every day at</label>
            <input id="s-time" type="time" value={time} onChange={(e) => setTime(e.target.value)} required className="input" />
            <p className="hint">Pick a time you're usually free: after college, after dinner…</p>
          </div>
          <button type="submit" disabled={loading || !name.trim()} className="btn btn-primary btn-block btn-lg">
            {loading ? "Creating…" : "Start my daily 10"}
          </button>
        </form>
      ) : (
        <form onSubmit={signIn} className="space-y-4">
          <div>
            <label htmlFor="s-code" className="label">Your 6-character code</label>
            <input
              id="s-code"
              value={code}
              onChange={(e) => setCodeInput(e.target.value.toUpperCase())}
              required
              maxLength={6}
              autoCapitalize="characters"
              className="input font-mono text-xl tracking-[0.35em]"
              placeholder="A1B2C3"
            />
            <p className="hint">It&apos;s on the Me tab of the phone you signed up on.</p>
          </div>
          <button type="submit" disabled={loading || code.trim().length < 6} className="btn btn-primary btn-block btn-lg">
            {loading ? "Checking…" : "Log in"}
          </button>
        </form>
      )}
      <p className="mt-5 text-center font-semibold text-ink-soft">
        Faculty?{" "}
        <Link href="/auth/faculty" className="font-extrabold text-tomato underline decoration-2 underline-offset-2">University login</Link>
      </p>
    </AuthShell>
  );
}
