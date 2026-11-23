"use client";

import Sidebar from "./Sidebar";

/** Sidebar + content column for faculty pages; subject pages get subject-specific links. */
export default function FacultyShell({ subject, children }: { subject?: string; children: React.ReactNode }) {
  const links = subject
    ? [
        { href: "/faculty", label: "All subjects" },
        { href: `/faculty/${subject}`, label: "Topics" },
        { href: `/faculty/${subject}/upload`, label: "Upload & generate" },
        { href: `/faculty/${subject}/review`, label: "Review questions" },
      ]
    : [{ href: "/faculty", label: "All subjects" }];
  return (
    <div className="flex min-h-[calc(100dvh-60px)] flex-col md:flex-row">
      <Sidebar links={links} />
      <div className="min-w-0 flex-1 px-4 py-8 sm:px-8">{children}</div>
    </div>
  );
}
