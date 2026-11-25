"""
Data model. Content (subjects, topics, questions) is shared by every student taking a
subject and generated once; only progress (enrollments, reviews, sessions) is per student.

SQLite by default; set STUDY_DATABASE_URL=postgresql+psycopg://... for Postgres. Indexes
cover the hot queries: a student's due reviews, a subject's approved questions per topic.
"""

import os
from datetime import date, datetime, timezone

from sqlalchemy import (
    JSON,
    Boolean,
    Date,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
    create_engine,
)
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship, sessionmaker


def _now() -> datetime:
    return datetime.now(timezone.utc)


class Base(DeclarativeBase):
    pass


class Subject(Base):
    __tablename__ = "subjects"

    id: Mapped[int] = mapped_column(primary_key=True)
    code: Mapped[str] = mapped_column(String(32), unique=True)          # e.g. "21CS53"
    name: Mapped[str] = mapped_column(String(200))
    department: Mapped[str] = mapped_column(String(64), default="")
    semester: Mapped[int] = mapped_column(Integer, default=0)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)

    topics: Mapped[list["Topic"]] = relationship(back_populates="subject", order_by="Topic.position")


class Topic(Base):
    """One daily bite: a few pages of the notes, in syllabus order."""

    __tablename__ = "topics"
    __table_args__ = (UniqueConstraint("subject_id", "position"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    subject_id: Mapped[int] = mapped_column(ForeignKey("subjects.id", ondelete="CASCADE"), index=True)
    position: Mapped[int] = mapped_column(Integer)                       # syllabus order
    source: Mapped[str] = mapped_column(String(300))                     # "dbms_notes.pdf, part 4"
    text: Mapped[str] = mapped_column(Text)                              # the notes for this topic
    title: Mapped[str] = mapped_column(String(200), default="")
    summary: Mapped[str] = mapped_column(Text, default="")
    key_points: Mapped[list] = mapped_column(JSON, default=list)
    exam_weight: Mapped[int] = mapped_column(Integer, default=0)         # marks asked in past papers
    # The "explain simply" layer: plain words, an everyday analogy, and the topic's jargon defined.
    # Faculty review it like questions (an analogy can be subtly wrong); students see it only when approved.
    simple_explanation: Mapped[str] = mapped_column(Text, default="")
    analogy: Mapped[str] = mapped_column(Text, default="")
    glossary: Mapped[list] = mapped_column(JSON, default=list)           # [{"term", "meaning"}]
    simple_status: Mapped[str] = mapped_column(String(16), default="")   # "" (none) | draft | approved | rejected

    subject: Mapped[Subject] = relationship(back_populates="topics")
    questions: Mapped[list["Question"]] = relationship(back_populates="topic")
    past_questions: Mapped[list["PastQuestion"]] = relationship(back_populates="topic")


class Question(Base):
    """A multiple-choice question generated from one topic's notes."""

    __tablename__ = "questions"
    __table_args__ = (Index("ix_questions_topic_status", "topic_id", "status"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    topic_id: Mapped[int] = mapped_column(ForeignKey("topics.id", ondelete="CASCADE"))
    prompt: Mapped[str] = mapped_column(Text)
    options: Mapped[list] = mapped_column(JSON)
    answer_index: Mapped[int] = mapped_column(Integer)
    explanation: Mapped[str] = mapped_column(Text, default="")
    evidence: Mapped[str] = mapped_column(Text, default="")              # quote from the notes
    level: Mapped[str] = mapped_column(String(8), default="core")        # warmup | core | exam
    # draft -> approved | rejected (faculty); auto_rejected = failed the grounding check
    status: Mapped[str] = mapped_column(String(16), default="draft")
    status_reason: Mapped[str] = mapped_column(String(300), default="")
    reports: Mapped[int] = mapped_column(Integer, default=0)            # "this question is wrong"

    topic: Mapped[Topic] = relationship(back_populates="questions")


class PastQuestion(Base):
    """A question from a previous exam paper, matched to the topic it belongs to."""

    __tablename__ = "past_questions"

    id: Mapped[int] = mapped_column(primary_key=True)
    subject_id: Mapped[int] = mapped_column(ForeignKey("subjects.id", ondelete="CASCADE"), index=True)
    topic_id: Mapped[int | None] = mapped_column(ForeignKey("topics.id", ondelete="SET NULL"), index=True)
    text: Mapped[str] = mapped_column(Text)
    year: Mapped[int | None] = mapped_column(Integer)
    marks: Mapped[int | None] = mapped_column(Integer)

    topic: Mapped[Topic | None] = relationship(back_populates="past_questions")


class Student(Base):
    __tablename__ = "students"

    id: Mapped[int] = mapped_column(primary_key=True)
    code: Mapped[str] = mapped_column(String(16), unique=True)          # internal id; not a login
    email: Mapped[str | None] = mapped_column(String(254), unique=True)  # college email: how students sign in
    password_hash: Mapped[str | None] = mapped_column(String(300))       # scrypt; None until a password is set
    name: Mapped[str] = mapped_column(String(120))
    notify_time: Mapped[str] = mapped_column(String(5), default="19:00")  # HH:MM, local time
    telegram_chat_id: Mapped[str | None] = mapped_column(String(32))
    last_notified_on: Mapped[date | None] = mapped_column(Date)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)

    enrollments: Mapped[list["Enrollment"]] = relationship(back_populates="student")


class Enrollment(Base):
    __tablename__ = "enrollments"
    __table_args__ = (UniqueConstraint("student_id", "subject_id"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    student_id: Mapped[int] = mapped_column(ForeignKey("students.id", ondelete="CASCADE"), index=True)
    subject_id: Mapped[int] = mapped_column(ForeignKey("subjects.id", ondelete="CASCADE"))
    start_date: Mapped[date] = mapped_column(Date)
    exam_date: Mapped[date] = mapped_column(Date)

    student: Mapped[Student] = relationship(back_populates="enrollments")
    subject: Mapped[Subject] = relationship()


class TopicProgress(Base):
    """When a student was first taught a topic (its concept card)."""

    __tablename__ = "topic_progress"
    __table_args__ = (UniqueConstraint("student_id", "topic_id"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    student_id: Mapped[int] = mapped_column(ForeignKey("students.id", ondelete="CASCADE"), index=True)
    topic_id: Mapped[int] = mapped_column(ForeignKey("topics.id", ondelete="CASCADE"))
    learned_on: Mapped[date] = mapped_column(Date)


class Review(Base):
    """Spaced-repetition state of one question for one student (Leitner box + next due date)."""

    __tablename__ = "reviews"
    __table_args__ = (
        UniqueConstraint("student_id", "question_id"),
        Index("ix_reviews_student_due", "student_id", "due_on"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    student_id: Mapped[int] = mapped_column(ForeignKey("students.id", ondelete="CASCADE"))
    question_id: Mapped[int] = mapped_column(ForeignKey("questions.id", ondelete="CASCADE"))
    box: Mapped[int] = mapped_column(Integer, default=0)
    due_on: Mapped[date] = mapped_column(Date)
    attempts: Mapped[int] = mapped_column(Integer, default=0)
    correct: Mapped[int] = mapped_column(Integer, default=0)
    last_answered_on: Mapped[date | None] = mapped_column(Date)


class Faculty(Base):
    """A university staff account: uploads subjects and approves questions."""

    __tablename__ = "faculty"

    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(120))
    email: Mapped[str] = mapped_column(String(200), unique=True)
    password_hash: Mapped[str] = mapped_column(String(300))
    department: Mapped[str] = mapped_column(String(64), default="")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)


class FacultyToken(Base):
    """A login session. Only a hash of the token is stored, so a database leak can't be replayed."""

    __tablename__ = "faculty_tokens"

    id: Mapped[int] = mapped_column(primary_key=True)
    faculty_id: Mapped[int] = mapped_column(ForeignKey("faculty.id", ondelete="CASCADE"), index=True)
    token_hash: Mapped[str] = mapped_column(String(64), unique=True)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))


class StudentToken(Base):
    """A signed-in device. Only a hash of the token is stored. Expiry slides forward while the
    device is in use (see student_auth.student_for_token), up to an absolute limit from created_at."""

    __tablename__ = "student_tokens"

    id: Mapped[int] = mapped_column(primary_key=True)
    student_id: Mapped[int] = mapped_column(ForeignKey("students.id", ondelete="CASCADE"), index=True)
    token_hash: Mapped[str] = mapped_column(String(64), unique=True)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)
    user_agent: Mapped[str | None] = mapped_column(String(200))           # "which devices am I signed in on"


class OneTimeCode(Base):
    """
    Short-lived single-use codes, stored hashed: "reset" tokens are emailed as password-reset links;
    "telegram" codes link a signed-in student's Telegram chat.
    """

    __tablename__ = "one_time_codes"

    id: Mapped[int] = mapped_column(primary_key=True)
    purpose: Mapped[str] = mapped_column(String(16))
    email: Mapped[str | None] = mapped_column(String(254), index=True)
    student_id: Mapped[int | None] = mapped_column(ForeignKey("students.id", ondelete="CASCADE"))
    code_hash: Mapped[str] = mapped_column(String(64), index=True)
    attempts: Mapped[int] = mapped_column(Integer, default=0)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)


class AuthAttempt(Base):
    """One rate-limited auth event (a code sent, a code checked, a password tried), by key."""

    __tablename__ = "auth_attempts"
    __table_args__ = (Index("ix_auth_attempts_key_time", "key", "created_at"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    key: Mapped[str] = mapped_column(String(300))          # e.g. "code-ip:203.0.113.7"
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now, index=True)


class DailySession(Base):
    """The session built for a student on a day: fixed once built, so reloading shows the same one."""

    __tablename__ = "daily_sessions"
    __table_args__ = (UniqueConstraint("student_id", "day"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    student_id: Mapped[int] = mapped_column(ForeignKey("students.id", ondelete="CASCADE"))
    day: Mapped[date] = mapped_column(Date)
    plan: Mapped[dict] = mapped_column(JSON)
    completed: Mapped[bool] = mapped_column(Boolean, default=False)


class AssistantConversation(Base):
    """A chat with the in-app assistant. Owned by one student or one faculty member."""

    __tablename__ = "assistant_conversations"

    id: Mapped[str] = mapped_column(String(36), primary_key=True)          # uuid
    owner_kind: Mapped[str] = mapped_column(String(8))                     # student | faculty
    owner_id: Mapped[int] = mapped_column(Integer, index=True)
    title: Mapped[str] = mapped_column(String(120), default="New chat")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)


class AssistantMessage(Base):
    """
    One message in the model's own format: user text, an assistant reply (text and/or tool calls),
    or a tool result. `events` keeps what the UI showed for this turn (plan, steps, cards), so a
    conversation reopens exactly as it looked.
    """

    __tablename__ = "assistant_messages"

    id: Mapped[int] = mapped_column(primary_key=True)
    conversation_id: Mapped[str] = mapped_column(ForeignKey("assistant_conversations.id", ondelete="CASCADE"), index=True)
    role: Mapped[str] = mapped_column(String(10))                          # user | assistant | tool
    content: Mapped[str] = mapped_column(Text, default="")
    tool_calls: Mapped[list | None] = mapped_column(JSON)                  # assistant: [{id, name, args}]
    tool_call_id: Mapped[str | None] = mapped_column(String(64))           # tool: which call this answers
    name: Mapped[str | None] = mapped_column(String(64))                   # tool: tool name
    events: Mapped[list | None] = mapped_column(JSON)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)


class PendingAction(Base):
    """A change the assistant proposed; it runs only after the user approves it in the chat."""

    __tablename__ = "assistant_pending_actions"

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    conversation_id: Mapped[str] = mapped_column(ForeignKey("assistant_conversations.id", ondelete="CASCADE"), index=True)
    tool_call_id: Mapped[str] = mapped_column(String(64))
    tool: Mapped[str] = mapped_column(String(64))
    args: Mapped[dict] = mapped_column(JSON)
    summary: Mapped[str] = mapped_column(Text)
    status: Mapped[str] = mapped_column(String(10), default="pending")    # pending | approved | rejected
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)


_engine = None
_Session = None


def database_url() -> str:
    return os.getenv("STUDY_DATABASE_URL", "sqlite:///daily10.sqlite")


def init(url: str | None = None, reset: bool = False):
    """Create the engine and tables (idempotent). Tests pass "sqlite://" for an in-memory DB,
    or a Postgres URL with reset=True to start each test from empty tables."""
    global _engine, _Session
    url = url or database_url()
    kwargs = {"connect_args": {"check_same_thread": False}} if url.startswith("sqlite") else {"pool_pre_ping": True}
    if _engine is not None:
        _engine.dispose()
    if url in ("sqlite://", "sqlite:///:memory:"):
        from sqlalchemy.pool import StaticPool

        kwargs["poolclass"] = StaticPool
    _engine = create_engine(url, **kwargs)
    if reset:
        Base.metadata.drop_all(_engine)
    Base.metadata.create_all(_engine)
    _migrate(_engine)
    _Session = sessionmaker(_engine, expire_on_commit=False)
    return _engine


# Columns added after the first release. create_all() makes new tables but never changes an
# existing one, so these are added in place (nullable or with a default, so existing rows stay valid).
_ADDED_COLUMNS = [
    ("students", "email", "VARCHAR(254)", "CREATE UNIQUE INDEX IF NOT EXISTS ix_students_email ON students (email)"),
    ("topics", "simple_explanation", "TEXT DEFAULT ''", None),
    ("topics", "analogy", "TEXT DEFAULT ''", None),
    ("topics", "glossary", "JSON DEFAULT '[]'", None),
    ("topics", "simple_status", "VARCHAR(16) DEFAULT ''", None),
    ("questions", "level", "VARCHAR(8) DEFAULT 'core'", None),
    ("student_tokens", "user_agent", "VARCHAR(200)", None),
    ("students", "password_hash", "VARCHAR(300)", None),
]


def _migrate(engine) -> None:
    from sqlalchemy import inspect, text

    inspector = inspect(engine)
    with engine.begin() as conn:
        for table, column, sql_type, index_sql in _ADDED_COLUMNS:
            if column not in {c["name"] for c in inspector.get_columns(table)}:
                conn.execute(text(f"ALTER TABLE {table} ADD COLUMN {column} {sql_type}"))
                if index_sql:
                    conn.execute(text(index_sql))


def session():
    if _Session is None:
        init()
    return _Session()
