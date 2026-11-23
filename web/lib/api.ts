// Typed client for the Daily 10 API. Requests go to /api/study/*, which Next.js proxies
// to the FastAPI backend (see next.config.ts).

export type Card = {
  topic_id: number;
  subject: string;
  title: string;
  summary: string;
  key_points: string[];
  source: string;
  exam_weight: number;
};

export type SessionQuestion = {
  id: number;
  topic: string;
  prompt: string;
  options: string[];
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
  code: string;
  name: string;
  notify_time: string;
  telegram_linked: boolean;
  subjects: { code: string; name: string; exam_date: string }[];
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
};
export type ReviewQuestion = {
  id: number;
  topic: string;
  prompt: string;
  options: string[];
  answer_index: number;
  explanation: string;
  evidence: string;
  status: string;
  status_reason: string;
  reports: number;
};
export type GenerateStats = { topics: number; draft: number; auto_rejected: number; failed_topics: number };

async function call<T>(method: string, path: string, body?: unknown, token?: string): Promise<T> {
  let res: Response;
  const headers: Record<string, string> = {};
  if (body && !(body instanceof FormData)) headers["content-type"] = "application/json";
  if (token) headers["authorization"] = `Bearer ${token}`;
  try {
    res = await fetch(`/api/study${path}`, {
      method,
      headers,
      body: body instanceof FormData ? body : body ? JSON.stringify(body) : undefined,
      cache: "no-store",
    });
  } catch {
    throw new ApiError(0, "Can't reach the server. Check your connection and try again.");
  }
  if (!res.ok) {
    let detail = res.statusText;
    try {
      const data = await res.json();
      detail = typeof data.detail === "string" ? data.detail : JSON.stringify(data.detail);
    } catch {}
    throw new ApiError(res.status, detail || `Request failed (${res.status})`);
  }
  return res.json() as Promise<T>;
}

export const api = {
  register: (name: string, notify_time: string) =>
    call<{ code: string; name: string; notify_time: string }>("POST", "/students", { name, notify_time }),
  profile: (code: string) => call<Profile>("GET", `/students/${code}`),
  updateReminder: (code: string, notify_time: string) => call("PATCH", `/students/${code}`, { notify_time }),
  subjects: () => call<Subject[]>("GET", "/subjects"),
  enroll: (code: string, subject_code: string, exam_date: string) =>
    call("POST", `/students/${code}/enroll`, { subject_code, exam_date }),
  today: (code: string) => call<Session>("GET", `/students/${code}/today`),
  answer: (code: string, question_id: number, chosen_index: number) =>
    call<AnswerResult>("POST", `/students/${code}/answers`, { question_id, chosen_index }),
  report: (question_id: number) => call("POST", `/questions/${question_id}/report`),
  progress: (code: string) => call<Progress>("GET", `/students/${code}/progress`),

  // Faculty
  facultyRegister: (b: { name: string; email: string; password: string; department: string; invite_code: string }) =>
    call<{ token: string; faculty: FacultyInfo }>("POST", "/faculty/register", b),
  facultyLogin: (email: string, password: string) =>
    call<{ token: string; faculty: FacultyInfo }>("POST", "/faculty/login", { email, password }),
  facultyLogout: (token: string) => call("POST", "/faculty/logout", undefined, token),
  createSubject: (t: string, b: { code: string; name: string; department: string; semester: number }) =>
    call<{ code: string; name: string }>("POST", "/subjects", b, t),
  uploadNotes: (t: string, code: string, files: File[]) => {
    const fd = new FormData();
    files.forEach((f) => fd.append("files", f));
    return call<{ topics_added: number }>("POST", `/subjects/${code}/notes`, fd, t);
  },
  uploadPaper: (t: string, code: string, file: File, year?: number) => {
    const fd = new FormData();
    fd.append("file", file);
    if (year) fd.append("year", String(year));
    return call<{ questions_found: number }>("POST", `/subjects/${code}/past-papers`, fd, t);
  },
  generate: (t: string, code: string, limit: number) =>
    call<GenerateStats>("POST", `/subjects/${code}/generate?limit=${limit}`, undefined, t),
  check: (t: string, code: string) =>
    call<{ checked: number; passed: number; flagged: number; errors: number }>("POST", `/subjects/${code}/check`, undefined, t),
  topics: (code: string) => call<TopicRow[]>("GET", `/subjects/${code}/topics`),
  questions: (t: string, code: string, status?: string) =>
    call<ReviewQuestion[]>("GET", `/subjects/${code}/questions${status ? `?status=${status}` : ""}`, undefined, t),
  setStatus: (t: string, id: number, status: "approved" | "rejected") =>
    call("POST", `/questions/${id}/status`, { status }, t),
};
