"use client";

import Link from "next/link";
import { usePathname, useRouter } from "next/navigation";
import { useEffect, useState } from "react";
import { api } from "@/lib/api";
import { clearCode, clearFaculty, getCode, getFaculty } from "@/lib/session";
import { SnappyHead } from "./Snappy";

export default function Navbar() {
  const pathname = usePathname();
  const router = useRouter();
  const [role, setRole] = useState<"student" | "faculty" | null>(null);

  // Re-check who is signed in on every route change.
  useEffect(() => {
    setRole(getFaculty() ? "faculty" : getCode() ? "student" : null);
  }, [pathname]);

  async function signOut() {
    const f = getFaculty();
    if (f) await api.facultyLogout(f.token).catch(() => {});
    clearFaculty();
    clearCode();
    setRole(null);
    router.replace("/");
  }

  return (
    <nav className="safe-top sticky top-0 z-40 border-b-[2.5px] border-ink bg-white">
      <div className="mx-auto flex max-w-6xl items-center justify-between gap-3 px-4 py-2.5 sm:px-6">
        <Link href={role === "faculty" ? "/faculty" : role === "student" ? "/today" : "/"} className="flex items-center gap-2" aria-label="Daily 10 home">
          <SnappyHead size={34} />
          <span className="font-display text-2xl font-extrabold leading-none">
            Daily<span className="text-tomato">10</span>
          </span>
        </Link>
        <div className="flex items-center gap-2 sm:gap-3">
          {role === "faculty" && (
            <Link href="/faculty" className="btn btn-white btn-sm hidden sm:inline-flex">My subjects</Link>
          )}
          {role ? (
            <button onClick={signOut} className="btn btn-sun btn-sm">Log out</button>
          ) : (
            <>
              <Link href="/auth/student" className="btn btn-primary btn-sm">Student</Link>
              <Link href="/auth/faculty" className="btn btn-white btn-sm">Faculty</Link>
            </>
          )}
        </div>
      </div>
    </nav>
  );
}
