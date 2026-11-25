// Typed client for the Daily 10 API. Requests go to /api/study/*, which Next.js proxies
// to the FastAPI backend (see next.config.ts).

import { clearFaculty, clearStudent } from "@/lib/session";

export type GlossaryTerm = { term: string; meaning: string };

// The "explain simply" layer of a topic: shown to students only after faculty approve it.
export type SimpleLayer = { explanation: string; analogy: string; glossary: GlossaryTerm[] };

export type Level = "warmup" | "core" | "exam";

export type Card = {
  topic_id: number;
  subject: string;
  title: string;
  summary: string;
  key_points: string[];
  source: string;
  exam_weight: number;
  simple: SimpleLayer | null;
  start_simple: boolean;
};

export type SessionQuestion = {
  id: number;
  topic: string;
  prompt: string;
  options: string[];
  level: Level;
  kind: "new" | "review";
  answered: boolean;
};

export type PastQuestion = { text: string; year: number | null; marks: number | null };

export type Session = {
  day: string;
  student: string;
  card: Card | null;
  questions: SessionQuestion[];
  past_question: PastQuestion | null;
  notes: string[];
  completed: boolean;
};

export type AnswerResult = {
  correct: boolean;
  answer_index: number;
  explanation: string;
  evidence: string;
  next_review: string;
  session_completed: boolean;
  simple: SimpleLayer | null; // only after a wrong answer, if the topic has an approved simple layer
};

export type SubjectProgress = {
  subject: string;
  code: string;
  exam_date: string;
  topics: number;
  covered: number;
  coverage: number;
  days_to_exam: number;
};

export type Progress = {
  student: string;
  subjects: SubjectProgress[];
  streak_days: number;
  accuracy: number | null;
  answers: number;
  weak_topics: { topic: string; misses: number }[];
};

export type Profile = {
  name: string;
  email: string | null;
  notify_time: string;
  telegram_linked: boolean;
  subjects: { code: string; name: string; exam_date: string }[];
  needs_profile: boolean;
};

export type Subject = { code: string; name: string; department: string; semester: number; topics: number };

export class ApiError extends Error {
  constructor(public status: number, message: string) {
    super(message);
  }
}

export type FacultyInfo = { name: string; email: string; department: string };
export type TopicRow = {
  id: number;
  position: number;
  title: string;
  source: string;
  exam_weight: number;
  questions: Partial<Record<"draft" | "approved" | "rejected" | "auto_rejected", number>>;
  simple_status: "" | "draft" | "approved" | "rejected";
};
export type ReviewQuestion = {
  id: number;
  topic: string;
  prompt: string;
  options: string[];
  answer_index: number;
  explanation: string;
  evidence: string;
  level: Level;
  status: string;
  status_reason: string;
  reports: number;
};
export type Explanation = {
  topic_id: number;
  position: number;
  title: string;
  summary: string;
  simple_explanation: string;
  analogy: string;
  glossary: GlossaryTerm[];
  status: "draft" | "approved" | "rejected";
};
export type ExplanationReview = {
  status: "approved" | "rejected" | "draft";
  simple_explanation?: string;
  analogy?: string;
  glossary?: GlossaryTerm[];
};
export type GenerateStats = {
  topics: number;
  draft: number;
  auto_rejected: number;
  failed_topics: number;
  simple_explanations: number;
  levels_tagged: number;
};

// Every request carries the session cookie (same origin) and the CSRF header the API requires for
// cookie-authenticated changes (see daily10/web_session.py). No token ever passes through JS.
async function call<T>(method: string, path: string, body?: unknown, role?: "student" | "faculty"): Promise<T> {
  let res: Response;
  const headers: Record<string, string> = { "x-requested-with": "daily10" };
  if (body && !(body instanceof FormData)) headers["content-type"] = "application/json";
  try {
    res = await fetch(`/api/study${path}`, {
      method,
      headers,
      body: body instanceof FormData ? body : body ? JSON.stringify(body) : undefined,
      credentials: "same-origin",
      cache: "no-store",
    });
  } catch {
    throw new ApiError(0, "Can't reach the server. Check your connection and try again.");
  }
  if (!res.ok) {
    let detail = res.statusText;
    try {
      const data = await res.json();
      detail = typeof data.detail === "string" ? data.detail : Array.isArray(data.detail) ? data.detail[0]?.msg ?? "Invalid input" : JSON.stringify(data.detail);
    } catch {}
    // A 401 on a signed-in call: the session expired or was logged out everywhere.
    if (res.status === 401 && role && typeof window !== "undefined") {
      if (role === "student") clearStudent();
      else clearFaculty();
      window.location.replace(role === "student" ? "/auth/student" : "/auth/faculty");
    }
    if (res.status === 429) detail = detail || "Too many attempts. Please wait a few minutes.";
    throw new ApiError(res.status, detail || `Request failed (${res.status})`);
  }
  return res.json() as Promise<T>;
}

const student = <T,>(method: string, path: string, body?: unknown) => call<T>(method, path, body, "student");
const faculty = <T,>(method: string, path: string, body?: unknown) => call<T>(method, path, body, "faculty");

export type SignedIn = { needs_profile: boolean; student: Profile };
export type ResetSent = { sent: boolean; expires_minutes: number };

export const api = {
  // Student accounts
  register: (b: { name: string; email: string; password: string; notify_time: string }) =>
    call<SignedIn>("POST", "/students/auth/register", b),
  login: (email: string, password: string) => call<SignedIn>("POST", "/students/auth/login", { email, password }),
  forgotPassword: (email: string) => call<ResetSent>("POST", "/students/auth/forgot-password", { email }),
  resetPassword: (token: string, password: string) =>
    call<SignedIn>("POST", "/students/auth/reset-password", { token, password }),
  changePassword: (current_password: string, new_password: string) =>
    student("POST", "/students/me/password", { current_password, new_password }),
  studentLogout: (everywhere = false) => call("POST", "/students/auth/logout", { everywhere }),

  // Signed-in student
  profile: () => student<Profile>("GET", "/students/me"),
  updateProfile: (b: { name?: string; notify_time?: string }) => student("PATCH", "/students/me", b),
  updateReminder: (notify_time: string) => student("PATCH", "/students/me", { notify_time }),
  subjects: () => call<Subject[]>("GET", "/subjects"),
  enroll: (subject_code: string, exam_date: string) => student("POST", "/students/me/enroll", { subject_code, exam_date }),
  today: () => student<Session>("GET", "/students/me/today"),
  answer: (question_id: number, chosen_index: number) =>
    student<AnswerResult>("POST", "/students/me/answers", { question_id, chosen_index }),
  report: (question_id: number) => student("POST", `/questions/${question_id}/report`),
  progress: () => student<Progress>("GET", "/students/me/progress"),
  telegramLink: () => student<{ code: string; url: string | null; expires_minutes: number }>("POST", "/students/me/telegram-link"),

  // Faculty
  facultyRegister: (b: { name: string; email: string; password: string; department: string; invite_code: string }) =>
    call<{ faculty: FacultyInfo }>("POST", "/faculty/register", b),
  facultyLogin: (email: string, password: string) => call<{ faculty: FacultyInfo }>("POST", "/faculty/login", { email, password }),
  facultyLogout: () => call("POST", "/faculty/logout"),
  createSubject: (b: { code: string; name: string; department: string; semester: number }) =>
    faculty<{ code: string; name: string }>("POST", "/subjects", b),
  uploadNotes: (code: string, files: File[]) => {
    const fd = new FormData();
    files.forEach((f) => fd.append("files", f));
    return faculty<{ topics_added: number }>("POST", `/subjects/${code}/notes`, fd);
  },
  uploadPaper: (code: string, file: File, year?: number) => {
    const fd = new FormData();
    fd.append("file", file);
    if (year) fd.append("year", String(year));
    return faculty<{ questions_found: number }>("POST", `/subjects/${code}/past-papers`, fd);
  },
  generate: (code: string, limit: number) => faculty<GenerateStats>("POST", `/subjects/${code}/generate?limit=${limit}`),
  check: (code: string) =>
    faculty<{ checked: number; passed: number; flagged: number; errors: number }>("POST", `/subjects/${code}/check`),
  topics: (code: string) => call<TopicRow[]>("GET", `/subjects/${code}/topics`),
  questions: (code: string, status?: string) =>
    faculty<ReviewQuestion[]>("GET", `/subjects/${code}/questions${status ? `?status=${status}` : ""}`),
  setStatus: (id: number, status: "approved" | "rejected") => faculty("POST", `/questions/${id}/status`, { status }),
  setLevel: (id: number, level: Level) => faculty<ReviewQuestion>("POST", `/questions/${id}/level`, { level }),
  explanations: (code: string, status?: string) =>
    faculty<Explanation[]>("GET", `/subjects/${code}/explanations${status ? `?status=${status}` : ""}`),
  reviewExplanation: (topicId: number, body: ExplanationReview) =>
    faculty<Explanation>("POST", `/topics/${topicId}/explanation`, body),
};
