"use client";

import { Fragment, useState } from "react";
import type { Citation } from "@/lib/assistant";

// A small, safe Markdown renderer for assistant replies (no HTML injection): headings, paragraphs,
// bullet / numbered lists, tables, **bold**, *italic*, `code`, and [T12#3] / [P7] citation chips.

const CITE = /\[((?:T\d+#\d+|P\d+)(?:\s*,\s*(?:T\d+#\d+|P\d+))*)\]/g;

function Inline({ text, onCite, known }: { text: string; onCite: (id: string) => void; known: Set<string> }) {
  const parts: React.ReactNode[] = [];
  let last = 0;
  let key = 0;
  for (const m of text.matchAll(CITE)) {
    parts.push(<Styled key={key++} text={text.slice(last, m.index)} />);
    for (const id of m[1].split(/\s*,\s*/)) {
      const ok = known.has(id);
      parts.push(
        <button
          key={key++}
          type="button"
          onClick={() => onCite(id)}
          title={ok ? "Show the source" : "Not found in what the assistant retrieved"}
          className={`mx-0.5 inline-flex translate-y-[-1px] items-center rounded-full border-2 border-ink px-1.5 text-[0.7rem] font-extrabold leading-4 ${ok ? "bg-sky-soft" : "bg-tomato-soft line-through"}`}
        >
          {id}
        </button>,
      );
    }
    last = (m.index ?? 0) + m[0].length;
  }
  parts.push(<Styled key={key++} text={text.slice(last)} />);
  return <>{parts}</>;
}

function Styled({ text }: { text: string }) {
  const out: React.ReactNode[] = [];
  const re = /(\*\*[^*]+\*\*|`[^`]+`|\*[^*\s][^*]*\*)/g;
  let last = 0;
  let k = 0;
  for (const m of text.matchAll(re)) {
    out.push(text.slice(last, m.index));
    const t = m[0];
    if (t.startsWith("**")) out.push(<strong key={k++}>{t.slice(2, -2)}</strong>);
    else if (t.startsWith("`")) out.push(<code key={k++} className="rounded bg-paper px-1 font-mono text-[0.9em]">{t.slice(1, -1)}</code>);
    else out.push(<em key={k++}>{t.slice(1, -1)}</em>);
    last = (m.index ?? 0) + t.length;
  }
  out.push(text.slice(last));
  return <>{out}</>;
}

type Block =
  | { kind: "h"; text: string }
  | { kind: "p"; text: string }
  | { kind: "ul" | "ol"; items: string[] }
  | { kind: "table"; rows: string[][] };

function parse(src: string): Block[] {
  const lines = src.replace(/\r/g, "").split("\n");
  const blocks: Block[] = [];
  let i = 0;
  while (i < lines.length) {
    const line = lines[i];
    if (!line.trim()) { i++; continue; }
    if (/^#{1,4}\s/.test(line)) { blocks.push({ kind: "h", text: line.replace(/^#+\s*/, "") }); i++; continue; }
    if (/^\s*\|/.test(line)) {
      const rows: string[][] = [];
      while (i < lines.length && /^\s*\|/.test(lines[i])) {
        const cells = lines[i].trim().replace(/^\||\|$/g, "").split("|").map((c) => c.trim());
        if (!cells.every((c) => /^:?-{2,}:?$/.test(c))) rows.push(cells);
        i++;
      }
      blocks.push({ kind: "table", rows });
      continue;
    }
    const bullet = /^\s*[-*•]\s+/;
    const numbered = /^\s*\d+[.)]\s+/;
    if (bullet.test(line) || numbered.test(line)) {
      const kind = bullet.test(line) ? "ul" : "ol";
      const re = kind === "ul" ? bullet : numbered;
      const items: string[] = [];
      while (i < lines.length && re.test(lines[i])) { items.push(lines[i].replace(re, "")); i++; }
      blocks.push({ kind, items });
      continue;
    }
    const para: string[] = [];
    while (i < lines.length && lines[i].trim() && !/^#{1,4}\s|^\s*\||^\s*[-*•]\s+|^\s*\d+[.)]\s+/.test(lines[i])) { para.push(lines[i]); i++; }
    blocks.push({ kind: "p", text: para.join(" ") });
  }
  return blocks;
}

export default function Markdown({ text, citations = [], unverified = [] }: { text: string; citations?: Citation[]; unverified?: string[] }) {
  const [open, setOpen] = useState<string | null>(null);
  const byId = new Map(citations.map((c) => [c.id, c]));
  const known = new Set(byId.keys());
  const show = (id: string) => setOpen((cur) => (cur === id ? null : id));
  const inline = (t: string) => <Inline text={t} onCite={show} known={known} />;
  const source = open ? byId.get(open) : null;

  return (
    <div className="flex flex-col gap-2 leading-relaxed">
      {parse(text).map((b, i) => (
        <Fragment key={i}>
          {b.kind === "h" && <p className="font-display text-lg font-extrabold">{inline(b.text)}</p>}
          {b.kind === "p" && <p>{inline(b.text)}</p>}
          {b.kind === "ul" && <ul className="ml-5 list-disc space-y-1">{b.items.map((t, j) => <li key={j}>{inline(t)}</li>)}</ul>}
          {b.kind === "ol" && <ol className="ml-5 list-decimal space-y-1">{b.items.map((t, j) => <li key={j}>{inline(t)}</li>)}</ol>}
          {b.kind === "table" && (
            <div className="overflow-x-auto">
              <table className="w-full border-collapse text-sm">
                <tbody>
                  {b.rows.map((r, j) => (
                    <tr key={j} className={j === 0 ? "bg-sun-soft font-extrabold" : "border-t border-ink/20"}>
                      {r.map((c, k) => <td key={k} className="px-2 py-1 align-top">{inline(c)}</td>)}
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}
        </Fragment>
      ))}
      {open && (
        <div className="sticker-flat bg-sky-soft p-3 text-sm">
          <div className="mb-1 flex items-center justify-between gap-2">
            <span className="font-extrabold">{open}{source?.topic ? ` · ${source.topic}` : ""}{source?.year ? ` · ${source.year}` : ""}</span>
            <button type="button" onClick={() => setOpen(null)} className="font-bold text-ink-soft" aria-label="Close source">✕</button>
          </div>
          {source ? <p className="max-h-56 overflow-y-auto whitespace-pre-line">{source.text}</p>
            : <p className="font-semibold text-[#7a1e0b]">The assistant didn&apos;t retrieve this passage, so this citation can&apos;t be trusted.</p>}
        </div>
      )}
      {unverified.length > 0 && (
        <p className="text-xs font-bold text-[#7a1e0b]">⚠ {unverified.join(", ")} {unverified.length === 1 ? "wasn't" : "weren't"} found in the retrieved notes.</p>
      )}
    </div>
  );
}
