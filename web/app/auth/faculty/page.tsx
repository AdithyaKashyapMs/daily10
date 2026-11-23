"use client";

import { useState } from "react";
import { useRouter } from "next/navigation";
import Link from "next/link";
import { api } from "@/lib/api";
import { setFaculty } from "@/lib/session";
import AuthShell from "@/components/AuthShell";

export default function FacultyLogin() {
  const router = useRouter();
  const [mode, setMode] = useState<"login" | "register">("login");
  const [form, setForm] = useState({ name: "", email: "", password: "", department: "CSE", invite_code: "" });
  const [error, setError] = useState("");
  const [loading, setLoading] = useState(false);
  const set = (k: keyof typeof form) => (e: React.ChangeEvent<HTMLInputElement>) => setForm({ ...form, [k]: e.target.value });

  async function submit(e: React.FormEvent) {
    e.preventDefault();
    setError("");
    setLoading(true);
    try {
      const res = mode === "login" ? await api.facultyLogin(form.email, form.password) : await api.facultyRegister(form);
      setFaculty({ token: res.token, ...res.faculty });
      router.replace("/faculty");
    } catch (err) {
      setError(err instanceof Error ? err.message : "Login failed");
    } finally {
      setLoading(false);
    }
  }

  return (
    <AuthShell
      block="block-sky"
      pose="papers"
      bubble={mode === "login" ? "Got new notes for me?" : "Welcome to the faculty room!"}
      tagline="Upload notes once. Every student in your class gets a daily plan."
      title={mode === "login" ? "University login" : "Create faculty account"}
      subtitle="For faculty and university staff."
    >
      <div className="mb-5 flex gap-2" role="tablist">
        <button role="tab" aria-selected={mode === "login"} onClick={() => setMode("login")} className="tab">Log in</button>
        <button role="tab" aria-selected={mode === "register"} onClick={() => setMode("register")} className="tab">New account</button>
      </div>
      {error && <p className="alert alert-error mb-4" role="alert">{error}</p>}
      <form onSubmit={submit} className="space-y-4">
        {mode === "register" && (
          <div className="grid gap-4 sm:grid-cols-[1fr_8rem]">
            <div>
              <label htmlFor="f-name" className="label">Full name</label>
              <input id="f-name" value={form.name} onChange={set("name")} required className="input" placeholder="Dr. Meera Rao" />
            </div>
            <div>
              <label htmlFor="f-dept" className="label">Department</label>
              <input id="f-dept" value={form.department} onChange={set("department")} className="input" />
            </div>
          </div>
        )}
        <div>
          <label htmlFor="f-email" className="label">College email</label>
          <input id="f-email" type="email" autoComplete="email" value={form.email} onChange={set("email")} required className="input" placeholder="you@college.edu" />
        </div>
        <div>
          <label htmlFor="f-password" className="label">Password</label>
          <input id="f-password" type="password" autoComplete={mode === "login" ? "current-password" : "new-password"} value={form.password} onChange={set("password")} required minLength={mode === "register" ? 8 : undefined} className="input" />
          {mode === "register" && <p className="hint">At least 8 characters.</p>}
        </div>
        {mode === "register" && (
          <div>
            <label htmlFor="f-invite" className="label">University invite code</label>
            <input id="f-invite" value={form.invite_code} onChange={set("invite_code")} className="input" />
            <p className="hint">Your college admin shares this, so only staff can create faculty accounts.</p>
          </div>
        )}
        <button type="submit" disabled={loading} className="btn btn-sky btn-block btn-lg">
          {loading ? "One moment…" : mode === "login" ? "Log in" : "Create account"}
        </button>
      </form>
      <p className="mt-5 text-center font-semibold text-ink-soft">
        Student?{" "}
        <Link href="/auth/student" className="font-extrabold text-tomato underline decoration-2 underline-offset-2">Student login</Link>
      </p>
    </AuthShell>
  );
}
