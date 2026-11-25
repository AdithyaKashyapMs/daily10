"use client";

import { useEffect, useState } from "react";
import { api } from "@/lib/api";
import { useStudent } from "@/lib/session";
import { BottomNav, Loading } from "@/components/BottomNav";
import Chat from "@/components/chat/Chat";

export default function StudyBuddy() {
  const ready = useStudent();
  const [name, setName] = useState<string | null>(null);

  useEffect(() => {
    if (ready) api.profile().then((p) => setName(p.name || "there")).catch(() => setName("there"));
  }, [ready]);

  return (
    <div className="flex h-[calc(100dvh-62px)] flex-col">
      <div className="mx-auto flex min-h-0 w-full max-w-md flex-1 flex-col px-4 pt-4">
        {ready && name ? <Chat role="student" name={name} compact /> : <Loading label="Waking up Study Buddy…" />}
      </div>
      <BottomNav />
    </div>
  );
}
