"use client";

import { useFaculty } from "@/lib/session";
import FacultyShell from "@/components/FacultyShell";
import { Loading } from "@/components/BottomNav";
import Chat from "@/components/chat/Chat";

export default function Copilot() {
  const me = useFaculty();
  return (
    <FacultyShell>
      <div className="mx-auto flex h-[calc(100dvh-62px-4rem)] min-h-[30rem] max-w-6xl flex-col">
        {me ? <Chat role="faculty" name={me.name} /> : <Loading label="Loading…" />}
      </div>
    </FacultyShell>
  );
}
