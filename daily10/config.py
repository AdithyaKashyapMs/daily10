"""Settings from environment variables (and a .env file in the repo root)."""

import os

from dotenv import load_dotenv

load_dotenv()

GROQ_API_KEY = os.getenv("GROQ_API_KEY")
GROQ_FALLBACK_API_KEY = os.getenv("GROQ_FALLBACK_API_KEY")
# Main model for generating lessons and questions, then fallbacks tried in order when it
# fails (e.g. its free-tier daily token limit is used up). Each model has its own limits.
MODEL = os.getenv("DAILY10_MODEL", "openai/gpt-oss-120b")
FALLBACK_MODELS = [m.strip() for m in os.getenv("DAILY10_FALLBACK_MODELS", "openai/gpt-oss-20b,qwen/qwen3.8-27b").split(",") if m.strip()]
# A different model family judges question quality, so it isn't grading its own work.
JUDGE_MODEL = os.getenv("DAILY10_JUDGE_MODEL", "qwen/qwen3.8-27b")

CHUNK_SIZE = int(os.getenv("CHUNK_SIZE", "1200"))
CHUNK_OVERLAP = int(os.getenv("CHUNK_OVERLAP", "200"))


# --- Deployment ------------------------------------------------------------------------------
# Read at call time (not import time) so tests and long-running workers see current values.

def timezone_name() -> str:
    """The college's timezone: "today", streaks and reminder times all use it, not the server's clock."""
    return os.getenv("STUDY_TIMEZONE", "Asia/Kolkata")


def local_now():
    from datetime import datetime
    from zoneinfo import ZoneInfo

    name = timezone_name()
    if name == "local":  # the machine's own zone (tests)
        return datetime.now().astimezone()
    return datetime.now(ZoneInfo(name))


def local_today():
    return local_now().date()


def app_url() -> str:
    """Where students open the app (used in reminder messages)."""
    return os.getenv("STUDY_APP_URL", "http://localhost:3000/today")


def app_origin() -> str:
    """The web app's origin (scheme + host), for links in emails, from STUDY_APP_URL."""
    from urllib.parse import urlsplit

    parts = urlsplit(app_url())
    return f"{parts.scheme}://{parts.netloc}"


def is_production() -> bool:
    return os.getenv("STUDY_ENV", "").lower() == "production"


def production_problems() -> list[str]:
    """Settings that must be in place before real students use the app."""
    problems = []
    if not os.getenv("STUDY_ADMIN_KEY"):
        problems.append("STUDY_ADMIN_KEY (university invite code) is not set: anyone could register as faculty")
    if not os.getenv("SMTP_HOST"):
        problems.append("SMTP_HOST is not set: students can't receive password-reset emails")
    if not os.getenv("STUDY_STUDENT_EMAIL_DOMAINS"):
        problems.append("STUDY_STUDENT_EMAIL_DOMAINS is not set: any email address could sign up as a student")
    if os.getenv("STUDY_DATABASE_URL", "sqlite").startswith("sqlite"):
        problems.append("STUDY_DATABASE_URL points at SQLite: use Postgres in production")
    return problems
