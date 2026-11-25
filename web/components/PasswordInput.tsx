"use client";

import { useState } from "react";

// A password field with a Show/Hide toggle: typing a password on a phone keyboard is error-prone.
export default function PasswordInput({
  id,
  value,
  onChange,
  autoComplete,
  minLength,
}: {
  id: string;
  value: string;
  onChange: (v: string) => void;
  autoComplete: "current-password" | "new-password";
  minLength?: number;
}) {
  const [shown, setShown] = useState(false);
  return (
    <div className="relative">
      <input
        id={id}
        type={shown ? "text" : "password"}
        value={value}
        onChange={(e) => onChange(e.target.value)}
        required
        minLength={minLength}
        maxLength={200}
        autoComplete={autoComplete}
        autoCapitalize="none"
        autoCorrect="off"
        spellCheck={false}
        className="input pr-20"
      />
      <button
        type="button"
        onClick={() => setShown((s) => !s)}
        aria-label={shown ? "Hide password" : "Show password"}
        aria-pressed={shown}
        className="absolute inset-y-0 right-2 my-auto h-9 px-2 text-sm font-extrabold text-ink-soft"
      >
        {shown ? "Hide" : "Show"}
      </button>
    </div>
  );
}
