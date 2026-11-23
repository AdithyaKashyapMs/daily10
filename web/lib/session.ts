"use client";

import { useEffect, useState } from "react";
import { useRouter } from "next/navigation";

// Two kinds of sign-in, kept apart:
//   students: a 6-character code (college email sign-in is a later step)
//   faculty:  an email/password login token from /study/faculty/login
const STUDENT = "daily10.code";
const FACULTY = "daily10.faculty";

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

export const getCode = () => read(STUDENT);
export const setCode = (code: string) => write(STUDENT, code.toUpperCase());
export const clearCode = () => write(STUDENT, null);

export type FacultySession = { token: string; name: string; email: string; department: string };
export function getFaculty(): FacultySession | null {
  const raw = read(FACULTY);
  try {
    return raw ? (JSON.parse(raw) as FacultySession) : null;
  } catch {
    return null;
  }
}
export const setFaculty = (s: FacultySession) => write(FACULTY, JSON.stringify(s));
export const clearFaculty = () => write(FACULTY, null);

/** The signed-in student's code; sends the user to the student login if there isn't one. */
export function useStudentCode(): string | null {
  const router = useRouter();
  const [code, setState] = useState<string | null>(null);
  useEffect(() => {
    // A link like /today?code=A1B2C3 (e.g. from a reminder) signs the student in on this device.
    const fromLink = new URLSearchParams(window.location.search).get("code");
    if (fromLink && /^[A-Za-z0-9]{6}$/.test(fromLink)) setCode(fromLink);
    const c = getCode();
    if (!c) router.replace("/auth/student");
    else setState(c);
  }, [router]);
  return code;
}

/** The signed-in faculty member; sends the user to the faculty login if there isn't one. */
export function useFaculty(): FacultySession | null {
  const router = useRouter();
  const [f, setState] = useState<FacultySession | null>(null);
  useEffect(() => {
    const s = getFaculty();
    if (!s) router.replace("/auth/faculty");
    else setState(s);
  }, [router]);
  return f;
}
