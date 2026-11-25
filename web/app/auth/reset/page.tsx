"use client";

import { Suspense, useState } from "react";
import { useRouter, useSearchParams } from "next/navigation";
import Link from "next/link";
import { api } from "@/lib/api";
import { markStudent } from "@/lib/session";
import AuthShell from "@/components/AuthShell";
import PasswordInput from "@/components/PasswordInput";

// Opened from the password-reset email: set a new password, which signs this device in and
// every other device out.
function ResetPassword() {
  const router = useRouter();
  const token = useSearchParams()?.get("token") ?? "";
  const [password, setPassword] = useState("");
  const [error, setError] = useState("");
  const [loading, setLoading] = useState(false);

  async function submit(e: React.FormEvent) {
    e.preventDefault();
    setError("");
    setLoading(true);
    try {
      const res = await api.resetPassword(token, password);
      markStudent();
      router.replace(res.needs_profile ? "/auth/student?step=profile" : "/today");
    } catch (err) {
      setError(err instanceof Error ? err.message : "Something went wrong. Try again.");
    } finally {
      setLoading(false);
    }
  }

  return (
    <AuthShell block="block-sun" pose="book" bubble="Fresh start!" tagline="Your syllabus, a little every day."
      title="Set a new password" subtitle="You'll be logged out on your other devices.">
      {!token ? (
        <p className="alert alert-error">This link is incomplete. Open the link from the email again, or ask for a new one.</p>
      ) : (
        <form onSubmit={submit} className="space-y-4">
          {error && <p className="alert alert-error" role="alert">{error}</p>}
          <div>
            <label htmlFor="r-password" className="label">New password</label>
            <PasswordInput id="r-password" value={password} onChange={setPassword} autoComplete="new-password" minLength={8} />
            <p className="hint">At least 8 characters.</p>
          </div>
          <button type="submit" disabled={loading || password.length < 8} className="btn btn-primary btn-block btn-lg">
            {loading ? "Saving…" : "Save and log in"}
          </button>
        </form>
      )}
      <p className="mt-5 text-center font-semibold text-ink-soft">
        <Link href="/auth/student" className="font-extrabold text-tomato underline decoration-2 underline-offset-2">Back to log in</Link>
      </p>
    </AuthShell>
  );
}

export default function ResetPasswordPage() {
  return (
    <Suspense>
      <ResetPassword />
    </Suspense>
  );
}
