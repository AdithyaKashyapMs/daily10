"use client";

import { useEffect, useState } from "react";
import { useRouter } from "next/navigation";

// Sessions are httpOnly cookies set by the API: the browser sends them on every request and page
// JavaScript can never read them, so an injected script can't steal a login. Route protection is in
// middleware.ts (it redirects before a protected page renders).
//
// What's stored here is only non-secret UI state:
//   STUDENT  "1" when this device signed in as a student (which home to show, the navbar)
//   FACULTY  the faculty member's name / email / department, for the header
const STUDENT = "daily10.signedIn.student";
const FACULTY = "daily10.signedIn.faculty";
// Before cookie sessions, raw login tokens were kept in localStorage. Never keep them around.
const LEGACY = ["daily10.student", "daily10.faculty", "daily10.code"];

function read(key: string): string | null {
  try {
    return localStorage.getItem(key);
  } catch {
    return null;
  }
}
function write(key: string, value: string | null) {
  try {
    if (value === null) localStorage.removeItem(key);
    else localStorage.setItem(key, value);
  } catch {}
}
function dropLegacyTokens() {
  LEGACY.forEach((k) => write(k, null));
}

export const isStudent = () => read(STUDENT) === "1";
export const markStudent = () => {
  dropLegacyTokens();
  write(STUDENT, "1");
};
export const clearStudent = () => write(STUDENT, null);

export type FacultyProfile = { name: string; email: string; department: string };
export function getFaculty(): FacultyProfile | null {
  const raw = read(FACULTY);
  try {
    return raw ? (JSON.parse(raw) as FacultyProfile) : null;
  } catch {
    return null;
  }
}
export const setFaculty = (p: FacultyProfile) => {
  dropLegacyTokens();
  write(FACULTY, JSON.stringify(p));
};
export const clearFaculty = () => write(FACULTY, null);

/** True once mounted on a signed-in student's device (middleware already sent everyone else away). */
export function useStudent(): boolean {
  const [ready, setReady] = useState(false);
  useEffect(() => {
    dropLegacyTokens();
    if (!isStudent()) write(STUDENT, "1"); // signed in on another tab or after an update: keep the hint right
    setReady(true);
  }, []);
  return ready;
}

/** The signed-in faculty member's profile (from cache, else the API); null while loading. */
export function useFaculty(): FacultyProfile | null {
  const router = useRouter();
  const [f, setState] = useState<FacultyProfile | null>(null);
  useEffect(() => {
    dropLegacyTokens();
    const cached = getFaculty();
    if (cached) return setState(cached);
    fetch("/api/study/faculty/me", { credentials: "same-origin", cache: "no-store" })
      .then(async (r) => {
        if (!r.ok) throw new Error();
        const p = (await r.json()) as FacultyProfile;
        setFaculty(p);
        setState(p);
      })
      .catch(() => router.replace("/auth/faculty"));
  }, [router]);
  return f;
}
