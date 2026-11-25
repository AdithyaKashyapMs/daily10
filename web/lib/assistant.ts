// Client for the assistant API (/study/assistant): replies stream as Server-Sent Events.

import { clearFaculty, clearStudent } from "@/lib/session";

export type Role = "student" | "faculty";

export type PlanStep = { title: string; status: "pending" | "in_progress" | "done" };
export type Citation = { id: string; topic: string | null; topic_id: number | null; text: string; year?: number | null };
export type QuizQuestion = { question_id: number; subject: string; topic_id: number; topic: string; prompt: string; options: string[] };

export type AEvent =
  | { type: "conversation"; id: string; title: string }
  | { type: "token"; text: string }
  | { type: "step"; id: string; tool: string; label: string; status: "running" | "done" | "error"; summary?: string; ms?: number }
  | { type: "plan"; steps: PlanStep[] }
  | { type: "quiz"; question: QuizQuestion }
  | { type: "answer"; question_id: number; correct: boolean; your_choice: string; correct_option: string; explanation: string; evidence_from_notes: string; next_review: string }
  | { type: "confirm"; action_id: string; tool: string; summary: string; args: Record<string, unknown> }
  | { type: "confirm_resolved"; action_id: string; status: "approved" | "rejected" | "expired" }
  | { type: "message"; text: string; citations: Citation[]; unverified: string[] }
  | { type: "waiting" }
  | { type: "error"; message: string }
  | { type: "done" };

export type Turn = { message: string; events: AEvent[] };
export type ConversationSummary = { id: string; title: string; updated_at: string };
export type Conversation = { id: string; title: string; role: Role; turns: Turn[]; pending: string[] };
export type Starter = { title: string; prompt: string };

function signOut(role: Role) {
  if (role === "student") clearStudent();
  else clearFaculty();
  window.location.replace(role === "student" ? "/auth/student" : "/auth/faculty");
}

// The session cookie authenticates; X-Daily10-Role picks the assistant if this browser is signed in
// as both a student and a faculty member; X-Requested-With is the API's CSRF check.
async function request(role: Role, method: string, path: string, body?: unknown, signal?: AbortSignal): Promise<Response> {
  let res: Response;
  try {
    res = await fetch(`/api/study/assistant${path}`, {
      method,
      headers: {
        "x-requested-with": "daily10",
        "x-daily10-role": role,
        ...(body ? { "content-type": "application/json" } : {}),
      },
      body: body ? JSON.stringify(body) : undefined,
      credentials: "same-origin",
      cache: "no-store",
      signal,
    });
  } catch (e) {
    if ((e as Error).name === "AbortError") throw e;
    throw new Error("Can't reach the server. Check your connection.");
  }
  if (res.status === 401) {
    signOut(role);
    throw new Error("Please sign in again.");
  }
  if (!res.ok) {
    let detail = res.statusText;
    try {
      detail = (await res.json()).detail ?? detail;
    } catch {}
    throw new Error(typeof detail === "string" ? detail : `Request failed (${res.status})`);
  }
  return res;
}

/** POST and read the event stream, calling onEvent for each event as it arrives. */
async function stream(role: Role, path: string, body: unknown, onEvent: (e: AEvent) => void, signal?: AbortSignal) {
  const res = await request(role, "POST", path, body, signal);
  const reader = res.body?.getReader();
  if (!reader) throw new Error("Streaming isn't supported in this browser.");
  const decoder = new TextDecoder();
  let buffer = "";
  for (;;) {
    const { value, done } = await reader.read();
    if (done) break;
    buffer += decoder.decode(value, { stream: true });
    let cut: number;
    while ((cut = buffer.indexOf("\n\n")) !== -1) {
      const chunk = buffer.slice(0, cut);
      buffer = buffer.slice(cut + 2);
      for (const line of chunk.split("\n")) {
        if (!line.startsWith("data: ")) continue;
        try {
          onEvent(JSON.parse(line.slice(6)) as AEvent);
        } catch {}
      }
    }
  }
}

export const assistant = {
  chat: (role: Role, message: string, conversationId: string | null, onEvent: (e: AEvent) => void, signal?: AbortSignal) =>
    stream(role, "/chat", { message, conversation_id: conversationId }, onEvent, signal),
  decide: (role: Role, conversationId: string, actionId: string, approve: boolean, onEvent: (e: AEvent) => void, signal?: AbortSignal) =>
    stream(role, `/conversations/${conversationId}/actions/${actionId}`, { approve }, onEvent, signal),
  list: async (role: Role) => (await request(role, "GET", "/conversations")).json() as Promise<ConversationSummary[]>,
  get: async (role: Role, id: string) => (await request(role, "GET", `/conversations/${id}`)).json() as Promise<Conversation>,
  remove: (role: Role, id: string) => request(role, "DELETE", `/conversations/${id}`),
  starters: async (role: Role) => (await request(role, "GET", "/starters")).json() as Promise<Starter[]>,
};
