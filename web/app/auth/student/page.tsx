"use client";

import { Suspense, useEffect, useState } from "react";
import { useRouter, useSearchParams } from "next/navigation";
import Link from "next/link";
import { api } from "@/lib/api";
import { markStudent } from "@/lib/session";
import AuthShell from "@/components/AuthShell";
import PasswordInput from "@/components/PasswordInput";

// Students log in with their college email and a password. The API sets an httpOnly session
// cookie for this device. "Forgot password?" emails a reset link (also how accounts made before
// passwords existed set their first one).
const LAST_EMAIL = "daily10.lastEmail"; // convenience only: prefill on this device
const MIN_PASSWORD = 8;

type Mode = "login" | "register" | "forgot" | "profile";

function StudentLogin() {
  const router = useRouter();
  const params = useSearchParams();
  const [mode, setMode] = useState<Mode>(params?.get("step") === "profile" ? "profile" : "login");
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [name, setName] = useState("");
  const [time, setTime] = useState("19:00");
  const [error, setError] = useState("");
  const [info, setInfo] = useState("");
  const [loading, setLoading] = useState(false);

  useEffect(() => {
    try {
      setEmail(localStorage.getItem(LAST_EMAIL) ?? "");
    } catch {}
  }, []);

  function switchTo(m: Mode) {
    setMode(m);
    setError("");
    setInfo("");
  }

  async function run(action: () => Promise<void>) {
    setError("");
    setInfo("");
    setLoading(true);
    try {
      await action();
    } catch (err) {
      setError(err instanceof Error ? err.message : "Something went wrong. Try again.");
    } finally {
      setLoading(false);
    }
  }

  function rememberEmail() {
    try {
      localStorage.setItem(LAST_EMAIL, email.trim().toLowerCase());
    } catch {}
  }

  const submit = (e: React.FormEvent) => {
    e.preventDefault();
    const clean = email.trim().toLowerCase();
    if (mode === "login") {
      run(async () => {
        const res = await api.login(clean, password);
        rememberEmail();
        markStudent();
        if (res.needs_profile) switchTo("profile");
        else router.replace("/today");
      });
    } else if (mode === "register") {
      run(async () => {
        await api.register({ name: name.trim(), email: clean, password, notify_time: time });
        rememberEmail();
        markStudent();
        router.replace("/settings?welcome=1");
      });
    } else if (mode === "forgot") {
      run(async () => {
        const res = await api.forgotPassword(clean);
        setInfo(`If ${clean} has an account, we've emailed a link to set a new password. It works for ${res.expires_minutes} minutes. Check spam too.`);
      });
    } else {
      run(async () => {
        await api.updateProfile({ name: name.trim(), notify_time: time });
        router.replace("/settings?welcome=1");
      });
    }
  };

  const titles: Record<Mode, [string, string, string]> = {
    login: ["Student login", "Use your college email and password.", "Ten minutes a day. Deal?"],
    register: ["Create your account", "Use your college email.", "Welcome aboard!"],
    forgot: ["Forgot password?", "We'll email you a link to set a new one.", "Happens to everyone!"],
    profile: ["One last thing", "So we know what to call you, and when to remind you.", "Nice to meet you!"],
  };
  const [title, subtitle, bubble] = titles[mode];

  const emailField = (
    <div>
      <label htmlFor="s-email" className="label">College email</label>
      <input
        id="s-email"
        type="email"
        value={email}
        onChange={(e) => setEmail(e.target.value)}
        required
        maxLength={254}
        autoComplete={mode === "register" ? "email" : "username"}
        autoCapitalize="none"
        autoCorrect="off"
        spellCheck={false}
        inputMode="email"
        className="input"
        placeholder="you@college.edu"
      />
    </div>
  );

  const nameAndTime = (
    <>
      <div>
        <label htmlFor="s-name" className="label">Your name</label>
        <input id="s-name" value={name} onChange={(e) => setName(e.target.value)} required maxLength={120}
          autoComplete="name" autoCapitalize="words" className="input" placeholder="Asha Rao" />
      </div>
      <div>
        <label htmlFor="s-time" className="label">Remind me every day at</label>
        <input id="s-time" type="time" value={time} onChange={(e) => setTime(e.target.value)} required className="input" />
        <p className="hint">Pick a time you&apos;re usually free: after college, after dinner…</p>
      </div>
    </>
  );

  const label = {
    login: loading ? "Logging in…" : "Log in",
    register: loading ? "Creating your account…" : "Start my daily 10",
    forgot: loading ? "Sending…" : "Email me a reset link",
    profile: loading ? "Saving…" : "Start my daily 10",
  }[mode];

  const disabled =
    loading ||
    (mode !== "profile" && !email.trim()) ||
    (mode === "login" && !password) ||
    (mode === "register" && (!name.trim() || password.length < MIN_PASSWORD)) ||
    (mode === "profile" && !name.trim());

  return (
    <AuthShell block="block-sun" pose="book" bubble={bubble}
      tagline="Your syllabus, a little every day. No panic in exam week." title={title} subtitle={subtitle}>
      {(mode === "login" || mode === "register") && (
        <div className="mb-5 flex gap-2" role="tablist">
          <button role="tab" aria-selected={mode === "login"} onClick={() => switchTo("login")} className="tab">Log in</button>
          <button role="tab" aria-selected={mode === "register"} onClick={() => switchTo("register")} className="tab">Create account</button>
        </div>
      )}
      {error && <p className="alert alert-error mb-4" role="alert">{error}</p>}
      {info && <p className="alert alert-ok mb-4" role="status">{info}</p>}

      <form onSubmit={submit} className="space-y-4">
        {mode === "register" && (
          <div>
            <label htmlFor="s-name" className="label">Your name</label>
            <input id="s-name" value={name} onChange={(e) => setName(e.target.value)} required maxLength={120}
              autoComplete="name" autoCapitalize="words" className="input" placeholder="Asha Rao" />
          </div>
        )}
        {mode !== "profile" && emailField}
        {(mode === "login" || mode === "register") && (
          <div>
            <div className="flex items-baseline justify-between">
              <label htmlFor="s-password" className="label">Password</label>
              {mode === "login" && (
                <button type="button" onClick={() => switchTo("forgot")} className="text-sm font-bold text-tomato underline">
                  Forgot password?
                </button>
              )}
            </div>
            <PasswordInput id="s-password" value={password} onChange={setPassword}
              autoComplete={mode === "login" ? "current-password" : "new-password"}
              minLength={mode === "register" ? MIN_PASSWORD : undefined} />
            {mode === "register" && <p className="hint">At least {MIN_PASSWORD} characters.</p>}
          </div>
        )}
        {mode === "register" && (
          <div>
            <label htmlFor="s-time" className="label">Remind me every day at</label>
            <input id="s-time" type="time" value={time} onChange={(e) => setTime(e.target.value)} required className="input" />
          </div>
        )}
        {mode === "profile" && nameAndTime}

        {!(mode === "forgot" && info) && (
          <button type="submit" disabled={disabled} className="btn btn-primary btn-block btn-lg">{label}</button>
        )}
        {mode === "forgot" && (
          <button type="button" onClick={() => switchTo("login")} className="block w-full py-2 text-center text-sm font-bold text-ink-soft underline">
            Back to log in
          </button>
        )}
      </form>

      {mode !== "profile" && (
        <p className="mt-5 text-center font-semibold text-ink-soft">
          Faculty?{" "}
          <Link href="/auth/faculty" className="font-extrabold text-tomato underline decoration-2 underline-offset-2">University login</Link>
        </p>
      )}
    </AuthShell>
  );
}

export default function StudentLoginPage() {
  return (
    <Suspense>
      <StudentLogin />
    </Suspense>
  );
}
