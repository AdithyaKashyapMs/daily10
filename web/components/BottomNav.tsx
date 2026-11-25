"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";

const TABS = [
  { href: "/today", label: "Today", emoji: "📖" },
  { href: "/assistant", label: "Ask", emoji: "💬" },
  { href: "/progress", label: "Progress", emoji: "🔥" },
  { href: "/settings", label: "Me", emoji: "🙂" },
];

/** Student tab bar: sticker pills, fixed at the bottom of the phone screen. */
export function BottomNav() {
  const path = usePathname();
  return (
    <nav className="safe-bottom sticky bottom-0 z-30 border-t-[2.5px] border-ink bg-white px-3 pt-2.5">
      <ul className="mx-auto grid max-w-md grid-cols-4 gap-1.5">
        {TABS.map((t) => {
          const active = path?.startsWith(t.href);
          return (
            <li key={t.href}>
              <Link href={t.href} aria-current={active ? "page" : undefined} className={`btn btn-sm btn-block !px-1 ${active ? "btn-primary" : "btn-white"}`}>
                <span aria-hidden>{t.emoji}</span> {t.label}
              </Link>
            </li>
          );
        })}
      </ul>
    </nav>
  );
}

/** Page frame for student screens: phone-width column above the tab bar. */
export function StudentFrame({ children }: { children: React.ReactNode }) {
  return (
    <div className="flex min-h-[calc(100dvh-60px)] flex-col">
      <div className="mx-auto flex w-full max-w-md flex-1 flex-col gap-4 px-4 py-6">{children}</div>
      <BottomNav />
    </div>
  );
}

export function Loading({ label }: { label: string }) {
  return (
    <div className="flex flex-1 flex-col items-center justify-center gap-3 py-16 font-semibold text-ink-soft" role="status">
      <span className="h-9 w-9 animate-spin rounded-full border-[3px] border-ink border-t-sun" />
      {label}
    </div>
  );
}
