"use client";

import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { assistant, type AEvent, type ConversationSummary, type PlanStep, type Role, type Starter, type Turn } from "@/lib/assistant";
import Snappy, { SnappyHead } from "@/components/Snappy";
import Markdown from "./Markdown";

// The assistant chat: streams each turn's events (plan, tool steps, cards, reply) as they happen.

type Step = Extract<AEvent, { type: "step" }>;
type Block =
  | { kind: "plan"; steps: PlanStep[] }
  | { kind: "activity"; steps: Step[]; notes: string[] }
  | { kind: "quiz"; event: Extract<AEvent, { type: "quiz" }> }
  | { kind: "answer"; event: Extract<AEvent, { type: "answer" }> }
  | { kind: "confirm"; event: Extract<AEvent, { type: "confirm" }>; status: string | null }
  | { kind: "message"; event: Extract<AEvent, { type: "message" }> }
  | { kind: "error"; message: string }
  | { kind: "live"; text: string };

/** Turn a turn's event stream into what to draw, in order. */
function blocks(events: AEvent[], streaming: boolean): Block[] {
  const out: Block[] = [];
  const resolved = new Map<string, string>();
  for (const e of events) if (e.type === "confirm_resolved") resolved.set(e.action_id, e.status);
  let plan: Extract<Block, { kind: "plan" }> | null = null;
  let activity: Extract<Block, { kind: "activity" }> | null = null;
  let live = "";
  const flushLive = () => {
    if (live.trim()) {
      if (!activity) out.push((activity = { kind: "activity", steps: [], notes: [] }));
      activity.notes.push(live.trim());
    }
    live = "";
  };
  for (const e of events) {
    switch (e.type) {
      case "token":
        live += e.text;
        break;
      case "plan":
        flushLive();
        if (plan) plan.steps = e.steps;
        else out.push((plan = { kind: "plan", steps: e.steps }));
        break;
      case "step": {
        if (e.tool === "update_plan") break; // shown as the plan card itself
        flushLive();
        if (!activity) out.push((activity = { kind: "activity", steps: [], notes: [] }));
        const i = activity.steps.findIndex((s) => s.id === e.id);
        if (i >= 0) activity.steps[i] = e;
        else activity.steps.push(e);
        break;
      }
      case "quiz":
        flushLive(); activity = null;
        out.push({ kind: "quiz", event: e });
        break;
      case "answer":
        flushLive(); activity = null;
        out.push({ kind: "answer", event: e });
        break;
      case "confirm":
        flushLive(); activity = null;
        out.push({ kind: "confirm", event: e, status: resolved.get(e.action_id) ?? null });
        break;
      case "message":
        live = "";
        out.push({ kind: "message", event: e });
        break;
      case "error":
        live = "";
        out.push({ kind: "error", message: e.message });
        break;
    }
  }
  if (streaming && live.trim()) out.push({ kind: "live", text: live });
  return out;
}

function PlanCard({ steps }: { steps: PlanStep[] }) {
  const done = steps.filter((s) => s.status === "done").length;
  return (
    <div className="sticker-flat bg-plum-soft p-3">
      <p className="mb-2 flex items-center justify-between text-sm font-extrabold">
        <span>📋 Plan</span>
        <span className="text-ink-soft">{done}/{steps.length}</span>
      </p>
      <ol className="space-y-1 text-sm font-semibold">
        {steps.map((s, i) => (
          <li key={i} className="flex items-start gap-2">
            <span aria-hidden className="w-5 shrink-0 text-center">{s.status === "done" ? "✅" : s.status === "in_progress" ? "⏳" : "▫️"}</span>
            <span className={s.status === "done" ? "text-ink-soft line-through" : ""}>{s.title}</span>
          </li>
        ))}
      </ol>
    </div>
  );
}

function Activity({ block, running }: { block: Extract<Block, { kind: "activity" }>; running: boolean }) {
  const active = running && block.steps.some((s) => s.status === "running");
  const ms = block.steps.reduce((t, s) => t + (s.ms ?? 0), 0);
  const n = block.steps.length;
  return (
    <details open={active || undefined} className="group rounded-2xl border-2 border-dashed border-ink/40 bg-white/60 px-3 py-2 text-sm">
      <summary className="flex cursor-pointer list-none items-center gap-2 font-bold text-ink-soft">
        {active ? <span className="h-3.5 w-3.5 animate-spin rounded-full border-2 border-ink border-t-sun" /> : <span aria-hidden>🛠️</span>}
        {active ? "Working…" : `Used ${n} tool${n === 1 ? "" : "s"}${ms >= 100 ? ` · ${(ms / 1000).toFixed(1)}s` : ""}`}
        <span className="ml-auto text-xs group-open:rotate-180">▾</span>
      </summary>
      <ul className="mt-2 space-y-1.5">
        {block.notes.map((t, i) => <li key={`n${i}`} className="italic text-ink-soft">💭 {t}</li>)}
        {block.steps.map((s) => (
          <li key={s.id} className="flex items-start gap-2">
            <span aria-hidden className="w-5 shrink-0 text-center">
              {s.status === "running" ? <span className="inline-block h-3 w-3 animate-spin rounded-full border-2 border-ink border-t-sun" /> : s.status === "done" ? "✓" : "⚠️"}
            </span>
            <span className="min-w-0">
              <span className="font-semibold">{s.label}</span>
              {s.summary && <span className={`ml-1.5 ${s.status === "error" ? "text-[#7a1e0b]" : "text-ink-soft"}`}>→ {s.summary}</span>}
            </span>
          </li>
        ))}
      </ul>
    </details>
  );
}

function QuizCard({ event, result, disabled, onAnswer }: {
  event: Extract<AEvent, { type: "quiz" }>; result?: Extract<AEvent, { type: "answer" }>; disabled: boolean; onAnswer: (letter: string) => void;
}) {
  const q = event.question;
  const answered = !!result;
  const right = result?.correct_option.slice(0, 1);
  return (
    <div className="sticker bg-white p-4">
      <p className="mb-1 text-xs font-extrabold uppercase tracking-wide text-ink-soft">{q.subject} · {q.topic}</p>
      <p className="mb-3 font-display text-lg font-extrabold leading-snug">{q.prompt}</p>
      <div className="flex flex-col gap-2">
        {q.options.map((o) => {
          const letter = o.slice(0, 1);
          return (
            <button key={o} type="button" disabled={answered || disabled} onClick={() => onAnswer(letter)}
              className={`option text-left ${letter === right ? "option-right" : letter === result?.your_choice ? "option-wrong" : answered ? "opacity-60" : ""}`}>
              <span className="option-letter">{letter}</span>
              <span>{o.slice(3)}</span>
            </button>
          );
        })}
      </div>
      {answered && <p className="mt-2 text-xs font-bold text-ink-soft">{result.correct ? "You got it ✓" : `You chose ${result.your_choice}`}</p>}
    </div>
  );
}

function AnswerCard({ event }: { event: Extract<AEvent, { type: "answer" }> }) {
  return (
    <div className={`sticker p-4 ${event.correct ? "bg-mint-soft" : "bg-tomato-soft"}`}>
      <p className="font-display text-xl font-extrabold">{event.correct ? "✅ Correct!" : `❌ You chose ${event.your_choice}`}</p>
      {!event.correct && <p className="mt-1 font-bold">Answer: {event.correct_option}</p>}
      {event.explanation && <p className="mt-2 font-semibold">{event.explanation}</p>}
      {event.evidence_from_notes && (
        <blockquote className="mt-2 border-l-4 border-ink/40 pl-3 text-sm italic">“{event.evidence_from_notes}”</blockquote>
      )}
      <p className="mt-2 text-xs font-bold text-ink-soft">Comes back for review on {new Date(event.next_review + "T00:00:00").toLocaleDateString(undefined, { day: "numeric", month: "short" })}</p>
    </div>
  );
}

function ConfirmCard({ block, canAct, onDecide }: {
  block: Extract<Block, { kind: "confirm" }>; canAct: boolean; onDecide: (approve: boolean) => void;
}) {
  const label = { approved: "✅ Approved", rejected: "Declined", expired: "Skipped (you moved on)" }[block.status ?? ""] ?? null;
  return (
    <div className="sticker bg-sun-soft p-4">
      <p className="text-xs font-extrabold uppercase tracking-wide text-ink-soft">Needs your OK</p>
      <p className="mt-1 font-display text-lg font-extrabold leading-snug">{block.event.summary}</p>
      {label ? (
        <p className="mt-2 font-bold">{label}</p>
      ) : (
        <div className="mt-3 flex gap-2">
          <button type="button" disabled={!canAct} onClick={() => onDecide(true)} className="btn btn-mint btn-sm flex-1">Approve</button>
          <button type="button" disabled={!canAct} onClick={() => onDecide(false)} className="btn btn-white btn-sm flex-1">Not now</button>
        </div>
      )}
    </div>
  );
}

function AssistantBubble({ children }: { children: React.ReactNode }) {
  return (
    <div className="flex items-start gap-2">
      <SnappyHead size={30} className="mt-1 shrink-0" />
      <div className="sticker-flat min-w-0 flex-1 bg-white px-4 py-3">{children}</div>
    </div>
  );
}

export default function Chat({ role, name, compact = false }: { role: Role; name: string; compact?: boolean }) {
  const [conversationId, setConversationId] = useState<string | null>(null);
  const [turns, setTurns] = useState<Turn[]>([]);
  const [pending, setPending] = useState<Set<string>>(new Set());
  const [busy, setBusy] = useState(false);
  const [input, setInput] = useState("");
  const [error, setError] = useState("");
  const [starters, setStarters] = useState<Starter[]>([]);
  const [history, setHistory] = useState<ConversationSummary[]>([]);
  const [showHistory, setShowHistory] = useState(!compact);
  const abort = useRef<AbortController | null>(null);
  const bottom = useRef<HTMLDivElement | null>(null);
  const idRef = useRef<string | null>(null);

  const refreshHistory = useCallback(() => {
    assistant.list(role).then(setHistory).catch(() => {});
  }, [role]);

  useEffect(() => {
    assistant.starters(role).then(setStarters).catch(() => {});
    refreshHistory();
  }, [role, refreshHistory]);

  useEffect(() => {
    bottom.current?.scrollIntoView({ behavior: "smooth", block: "end" });
  }, [turns]);

  const answers = useMemo(() => {
    const byQuestion = new Map<number, Extract<AEvent, { type: "answer" }>>();
    for (const t of turns) for (const e of t.events) if (e.type === "answer") byQuestion.set(e.question_id, e);
    return byQuestion;
  }, [turns]);

  const onEvent = useCallback((turnIndex: number) => (e: AEvent) => {
    if (e.type === "conversation") {
      idRef.current = e.id;
      setConversationId(e.id);
      return;
    }
    if (e.type === "done") return;
    if (e.type === "confirm") setPending((p) => new Set(p).add(e.action_id));
    if (e.type === "confirm_resolved") setPending((p) => { const n = new Set(p); n.delete(e.action_id); return n; });
    setTurns((ts) => ts.map((t, i) => (i === turnIndex ? { ...t, events: [...t.events, e] } : t)));
  }, []);

  async function run(turnIndex: number, go: (signal: AbortSignal) => Promise<void>) {
    setBusy(true);
    setError("");
    const ctrl = new AbortController();
    abort.current = ctrl;
    try {
      await go(ctrl.signal);
    } catch (e) {
      if ((e as Error).name !== "AbortError") {
        setTurns((ts) => ts.map((t, i) => (i === turnIndex ? { ...t, events: [...t.events, { type: "error", message: (e as Error).message }] } : t)));
      }
    } finally {
      setBusy(false);
      abort.current = null;
      refreshHistory();
    }
  }

  function send(text: string) {
    const msg = text.trim();
    if (!msg || busy) return;
    setInput("");
    const index = turns.length;
    setTurns((ts) => [...ts, { message: msg, events: [] }]);
    setPending(new Set()); // a new message declines anything still waiting
    run(index, (signal) => assistant.chat(role, msg, idRef.current, onEvent(index), signal));
  }

  function decide(turnIndex: number, actionId: string, approve: boolean) {
    if (busy || !idRef.current) return;
    const cid = idRef.current;
    run(turnIndex, (signal) => assistant.decide(role, cid, actionId, approve, onEvent(turnIndex), signal));
  }

  async function open(id: string) {
    if (busy) return;
    try {
      const c = await assistant.get(role, id);
      idRef.current = c.id;
      setConversationId(c.id);
      setTurns(c.turns);
      setPending(new Set(c.pending));
      if (compact) setShowHistory(false);
    } catch (e) {
      setError((e as Error).message);
    }
  }

  async function remove(id: string) {
    await assistant.remove(role, id).catch(() => {});
    if (id === idRef.current) newChat();
    refreshHistory();
  }

  function newChat() {
    if (busy) abort.current?.abort();
    idRef.current = null;
    setConversationId(null);
    setTurns([]);
    setPending(new Set());
    if (compact) setShowHistory(false);
  }

  const title = role === "student" ? "Study Buddy" : "Faculty Copilot";
  const first = name.split(" ")[0];

  const historyPanel = (
    <div className={compact ? "sticker-flat bg-white p-3" : "flex flex-col gap-2"}>
      <button type="button" onClick={newChat} className="btn btn-primary btn-sm btn-block">＋ New chat</button>
      {history.length === 0 && <p className="px-1 text-sm font-semibold text-ink-soft">No chats yet.</p>}
      <ul className="flex flex-col gap-1">
        {history.map((h) => (
          <li key={h.id} className="group flex items-center gap-1">
            <button type="button" onClick={() => open(h.id)}
              className={`min-w-0 flex-1 truncate rounded-xl px-2 py-1.5 text-left text-sm font-bold ${h.id === conversationId ? "bg-sun" : "hover:bg-white"}`}>
              {h.title}
            </button>
            <button type="button" onClick={() => remove(h.id)} aria-label={`Delete “${h.title}”`}
              className="rounded-lg px-1.5 text-ink-soft opacity-60 hover:opacity-100 sm:opacity-0 sm:group-hover:opacity-100">✕</button>
          </li>
        ))}
      </ul>
    </div>
  );

  return (
    <div className={`flex min-h-0 flex-1 gap-5 ${compact ? "flex-col" : "flex-row"}`}>
      {!compact && <aside className="hidden w-60 shrink-0 overflow-y-auto lg:block">{historyPanel}</aside>}

      <section className="flex min-h-0 min-w-0 flex-1 flex-col">
        <header className="mb-3 flex shrink-0 items-center justify-between gap-2">
          <h1 className="font-display text-3xl font-extrabold leading-none sm:text-4xl">{title}</h1>
          <div className={`flex gap-2 ${compact ? "" : "lg:hidden"}`}>
            <button type="button" onClick={() => setShowHistory((v) => !v)} className="btn btn-white btn-sm">Chats</button>
            <button type="button" onClick={newChat} className="btn btn-sun btn-sm">New</button>
          </div>
        </header>
        {showHistory && <div className={`mb-3 max-h-[40vh] overflow-y-auto ${compact ? "" : "lg:hidden"}`}>{historyPanel}</div>}
        {error && <p className="alert alert-error mb-3">{error}</p>}

        <div className="-mx-1 flex min-h-0 flex-1 flex-col gap-4 overflow-y-auto px-1 pb-4" aria-live="polite">
          {turns.length === 0 && (
            <div className="flex flex-col items-center gap-4 py-4 text-center">
              <Snappy pose={role === "student" ? "book" : "papers"} size={compact ? 110 : 130} />
              <p className="bubble max-w-sm">
                Hi {first}! {role === "student"
                  ? "I can explain topics, quiz you and plan your revision, all from your college's notes."
                  : "I can review questions, report on your class and draft new questions, and I'll ask before changing anything."}
              </p>
              <div className={`grid w-full gap-2 ${compact ? "grid-cols-1" : "grid-cols-1 sm:grid-cols-2"}`}>
                {starters.map((s) => (
                  <button key={s.title} type="button" onClick={() => send(s.prompt)} className="sticker-flat bg-white p-3 text-left transition hover:-translate-y-0.5">
                    <span className="block font-display text-lg font-extrabold">{s.title}</span>
                    <span className="block text-sm font-semibold text-ink-soft">{s.prompt}</span>
                  </button>
                ))}
              </div>
            </div>
          )}

          {turns.map((t, ti) => {
            const live = busy && ti === turns.length - 1;
            const bs = blocks(t.events, live);
            const thinking = live && !t.events.some((e) => e.type !== "token");
            return (
              <div key={ti} className="flex flex-col gap-3">
                <div className="flex justify-end">
                  <p className="sticker-flat max-w-[85%] whitespace-pre-wrap bg-sky-soft px-4 py-2.5 font-semibold">{t.message}</p>
                </div>
                {thinking && <AssistantBubble><span className="inline-flex items-center gap-2 font-bold text-ink-soft"><span className="h-3.5 w-3.5 animate-spin rounded-full border-2 border-ink border-t-sun" />Thinking…</span></AssistantBubble>}
                {bs.map((b, bi) => {
                  switch (b.kind) {
                    case "plan": return <PlanCard key={bi} steps={b.steps} />;
                    case "activity": return <Activity key={bi} block={b} running={live} />;
                    case "quiz": return <QuizCard key={bi} event={b.event} result={answers.get(b.event.question.question_id)} disabled={busy}
                      onAnswer={(l) => send(`My answer to question ${b.event.question.question_id}: ${l}`)} />;
                    case "answer": return <AnswerCard key={bi} event={b.event} />;
                    case "confirm": return <ConfirmCard key={bi} block={b} canAct={!busy && pending.has(b.event.action_id)}
                      onDecide={(ok) => decide(ti, b.event.action_id, ok)} />;
                    case "message": return b.event.text ? <AssistantBubble key={bi}><Markdown text={b.event.text} citations={b.event.citations} unverified={b.event.unverified} /></AssistantBubble> : null;
                    case "live": return <AssistantBubble key={bi}><Markdown text={b.text} /></AssistantBubble>;
                    case "error": return <p key={bi} className="alert alert-error">{b.message}</p>;
                  }
                })}
              </div>
            );
          })}
          <div ref={bottom} />
        </div>

        <form onSubmit={(e) => { e.preventDefault(); send(input); }}
          className="flex shrink-0 items-end gap-2 border-t-2 border-ink/10 bg-paper pt-3">
          <label htmlFor="chat-input" className="sr-only">Message</label>
          <textarea
            id="chat-input"
            value={input}
            onChange={(e) => setInput(e.target.value)}
            onKeyDown={(e) => { if (e.key === "Enter" && !e.shiftKey && !e.nativeEvent.isComposing) { e.preventDefault(); send(input); } }}
            rows={1}
            maxLength={4000}
            placeholder={role === "student" ? (compact ? "Ask, or say “quiz me”" : "Ask about your subjects, or say “quiz me”") : "Ask about questions, students or topics…"}
            className="input max-h-40 min-h-[3rem] flex-1 resize-none"
          />
          {busy
            ? <button type="button" onClick={() => abort.current?.abort()} className="btn btn-white">Stop</button>
            : <button type="submit" disabled={!input.trim()} className="btn btn-primary">Send</button>}
        </form>
        <p className="shrink-0 py-1.5 text-center text-xs font-semibold text-ink-soft">
          Answers come from your college&apos;s notes, with sources. Changes always ask you first.
        </p>
      </section>
    </div>
  );
}
