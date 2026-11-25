"""
Student accounts: college email + password, then a per-device session.

    register(email, password, name)  the email must be on a college domain (STUDY_STUDENT_EMAIL_DOMAINS);
                                     passwords are scrypt-hashed (same as faculty, auth.py).
    login(email, password)           FAILS_PER_EMAIL wrong passwords per account and FAILS_PER_IP per
                                     client IP per WINDOW_MINUTES; an unknown email costs the same work
                                     as a known one and gets the same error, so neither timing nor the
                                     reply reveals who has an account.
    request_password_reset(email)    emails a single-use link (RESET_MINUTES) if the account exists;
                                     the reply is the same either way. Accounts made before passwords
                                     existed set their first password this way.
    reset_password(token, password)  sets the password and signs every other device out.

The web app keeps the session token in an httpOnly cookie (web_session.py); other clients send
"Authorization: Bearer <token>". A session stays alive while it's used: each day of use pushes its
expiry TOKEN_DAYS out, up to MAX_SESSION_DAYS after sign-in.

Only hashes of passwords, reset tokens and session tokens are stored. Telegram is linked with a
separate single-use code a signed-in student gets from the app.
"""

import hashlib
import os
import re
import secrets
from datetime import datetime, timedelta, timezone

from sqlalchemy import delete, select

from daily10 import auth, db, ratelimit
from daily10.db import OneTimeCode, Student, StudentToken

MIN_PASSWORD = 8
FAILS_PER_EMAIL = 5
FAILS_PER_IP = 30
SIGNUPS_PER_IP = 20
RESETS_PER_EMAIL = 3
RESETS_PER_IP = 10
WINDOW_MINUTES = 15
RESET_MINUTES = 30
TOKEN_DAYS = 60               # idle timeout: unused this long, the session ends
MAX_SESSION_DAYS = 365        # absolute: sign in again after a year
TELEGRAM_CODE_MINUTES = 30

_EMAIL = re.compile(r"^[a-z0-9._%+\-]+@([a-z0-9\-]+\.)+[a-z]{2,}$")
_DUMMY_HASH = None


class AuthError(PermissionError):
    pass


RateLimited = ratelimit.RateLimited


def _hash(value: str) -> str:
    return hashlib.sha256(value.encode()).hexdigest()


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _aware(dt: datetime) -> datetime:
    return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)  # SQLite drops the timezone


def allowed_domains() -> list[str]:
    return [d.strip().lower().lstrip("@") for d in os.getenv("STUDY_STUDENT_EMAIL_DOMAINS", "").split(",") if d.strip()]


def normalize_email(email: str) -> str:
    email = (email or "").strip().lower()
    if not _EMAIL.match(email):
        raise ValueError("Enter a valid email address.")
    domains = allowed_domains()
    domain = email.split("@", 1)[1]
    if domains and not any(domain == d or domain.endswith("." + d) for d in domains):
        raise AuthError(f"Use your college email ({' or '.join('@' + d for d in domains)}).")
    return email


def _check_password(password: str) -> None:
    if len(password or "") < MIN_PASSWORD:
        raise ValueError(f"Password must be at least {MIN_PASSWORD} characters.")
    if len(password) > 200:
        raise ValueError("Password is too long.")


def needs_profile(student: Student) -> bool:
    """An account without a name (made before sign-up asked for one): the app asks for it."""
    return not (student.name or "").strip()


def register(email: str, password: str, name: str, notify_time: str = "19:00",
             ip: str | None = None, user_agent: str | None = None) -> tuple[str, Student]:
    """Create an account and sign this device in. Returns (session token, student)."""
    from daily10 import service

    email = normalize_email(email)
    _check_password(password)
    name = (name or "").strip()[:120]
    if not name:
        raise ValueError("Enter your name.")
    if ip:
        ratelimit.hit(f"signup-ip:{ip}", SIGNUPS_PER_IP, WINDOW_MINUTES)
    with db.session() as s:
        if s.scalar(select(Student.id).where(Student.email == email)) is not None:
            raise ValueError("An account with this email already exists. Log in, or use “Forgot password?”.")
    student = service.register_student(name, notify_time, email=email)
    with db.session() as s:
        s.get(Student, student.id).password_hash = auth.hash_password(password)
        s.commit()
    return issue_token(student.id, user_agent), student


def login(email: str, password: str, ip: str | None = None, user_agent: str | None = None) -> tuple[str, Student]:
    """Check email + password and sign this device in. Same error for every failure."""
    global _DUMMY_HASH
    email = (email or "").strip().lower()
    ratelimit.check(f"student-login:{email}", FAILS_PER_EMAIL, WINDOW_MINUTES)
    if ip:
        ratelimit.check(f"student-login-ip:{ip}", FAILS_PER_IP, WINDOW_MINUTES)
    with db.session() as s:
        student = s.scalar(select(Student).where(Student.email == email))
    stored = student.password_hash if student else None
    if stored is None:
        _DUMMY_HASH = _DUMMY_HASH or auth.hash_password(secrets.token_hex(8))
        auth.verify_password(password or "", _DUMMY_HASH)   # same work as a real check
    if stored is None or not auth.verify_password(password or "", stored):
        ratelimit.record(f"student-login:{email}")
        if ip:
            ratelimit.record(f"student-login-ip:{ip}")
        raise AuthError("Wrong email or password.")
    ratelimit.clear(f"student-login:{email}")
    return issue_token(student.id, user_agent), student


def change_password(student_id: int, current: str, new: str) -> None:
    _check_password(new)
    with db.session() as s:
        student = s.get(Student, student_id)
        if not student.password_hash or not auth.verify_password(current or "", student.password_hash):
            raise AuthError("Your current password is wrong.")
        student.password_hash = auth.hash_password(new)
        s.commit()


# --- Forgotten passwords -------------------------------------------------------------------

def request_password_reset(email: str, ip: str | None = None, sender=None) -> dict:
    """Email a reset link if the account exists. The reply is the same either way."""
    from daily10 import config, mailer

    email = normalize_email(email)
    reply = {"sent": True, "expires_minutes": RESET_MINUTES}
    if ip:
        ratelimit.hit(f"reset-ip:{ip}", RESETS_PER_IP, WINDOW_MINUTES)
    ratelimit.hit(f"reset:{email}", RESETS_PER_EMAIL, WINDOW_MINUTES)
    with db.session() as s:
        student = s.scalar(select(Student).where(Student.email == email))
        if student is None:
            return reply
        token = secrets.token_urlsafe(32)
        now = _now()
        s.execute(delete(OneTimeCode).where(OneTimeCode.purpose == "reset", OneTimeCode.student_id == student.id))
        s.add(OneTimeCode(purpose="reset", email=email, student_id=student.id, code_hash=_hash(token),
                          expires_at=now + timedelta(minutes=RESET_MINUTES), created_at=now))
        s.commit()
    (sender or mailer.send_password_reset)(email, f"{config.app_origin()}/auth/reset?token={token}")
    return reply


def reset_password(token: str, password: str, user_agent: str | None = None) -> tuple[str, Student]:
    """Set a new password from a reset link, sign out every device, and sign this one in."""
    _check_password(password)
    with db.session() as s:
        row = s.scalar(select(OneTimeCode).where(OneTimeCode.purpose == "reset", OneTimeCode.code_hash == _hash(token or "")))
        if row is None or _aware(row.expires_at) < _now():
            raise AuthError("This reset link has expired or was already used. Ask for a new one.")
        student = s.get(Student, row.student_id)
        student.password_hash = auth.hash_password(password)
        s.delete(row)
        s.execute(delete(StudentToken).where(StudentToken.student_id == student.id))
        s.commit()
    ratelimit.clear(f"student-login:{student.email}")
    return issue_token(student.id, user_agent), student


def issue_token(student_id: int, user_agent: str | None = None) -> str:
    token = secrets.token_urlsafe(32)
    now = _now()
    with db.session() as s:
        s.execute(delete(StudentToken).where(StudentToken.student_id == student_id, StudentToken.expires_at < now))
        s.add(StudentToken(student_id=student_id, token_hash=_hash(token), expires_at=now + timedelta(days=TOKEN_DAYS),
                           created_at=now, user_agent=(user_agent or "")[:200] or None))
        s.commit()
    return token


def student_for_token(token: str) -> Student | None:
    """The signed-in student, or None. Using a session pushes its expiry out (at most once a day)."""
    if not token:
        return None
    now = _now()
    with db.session() as s:
        row = s.scalar(select(StudentToken).where(StudentToken.token_hash == _hash(token)))
        if row is None:
            return None
        hard_limit = _aware(row.created_at) + timedelta(days=MAX_SESSION_DAYS)
        if _aware(row.expires_at) < now or hard_limit < now:
            return None
        renewed = min(now + timedelta(days=TOKEN_DAYS), hard_limit)
        if renewed - _aware(row.expires_at) > timedelta(days=1):
            row.expires_at = renewed
            s.commit()
        return s.get(Student, row.student_id)


def logout(token: str, everywhere: bool = False) -> None:
    with db.session() as s:
        row = s.scalar(select(StudentToken).where(StudentToken.token_hash == _hash(token)))
        if row is None:
            return
        if everywhere:
            s.execute(delete(StudentToken).where(StudentToken.student_id == row.student_id))
        else:
            s.delete(row)
        s.commit()


# --- Telegram linking ----------------------------------------------------------------------

def telegram_link_code(student_id: int) -> str:
    """Single-use code for t.me/<bot>?start=<code>, valid TELEGRAM_CODE_MINUTES."""
    code = secrets.token_urlsafe(12)
    now = _now()
    with db.session() as s:
        s.execute(delete(OneTimeCode).where(OneTimeCode.purpose == "telegram", OneTimeCode.student_id == student_id))
        s.add(OneTimeCode(purpose="telegram", student_id=student_id, code_hash=_hash(code),
                          expires_at=now + timedelta(minutes=TELEGRAM_CODE_MINUTES), created_at=now))
        s.commit()
    return code


def redeem_telegram_code(code: str) -> Student | None:
    with db.session() as s:
        row = s.scalar(select(OneTimeCode).where(OneTimeCode.purpose == "telegram",
                                                 OneTimeCode.code_hash == _hash(code or "")))
        if row is None:
            return None
        s.delete(row)
        s.commit()
        if _aware(row.expires_at) < _now():
            return None
        return s.get(Student, row.student_id)
