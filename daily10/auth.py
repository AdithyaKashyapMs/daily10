"""
Faculty accounts: email + password, and login tokens.

Passwords are hashed with scrypt (Python standard library, memory-hard) and a random salt.
Login returns a random token; the database stores only its SHA-256, and tokens expire after
TOKEN_DAYS. Registering needs the university's invite code (STUDY_ADMIN_KEY), so only staff
the university gives the code to can create faculty accounts.
"""

import hashlib
import hmac
import os
import secrets
from datetime import datetime, timedelta, timezone

from sqlalchemy import delete, func, select

from daily10 import db
from daily10.db import Faculty, FacultyToken

TOKEN_DAYS = 7
_SCRYPT = dict(n=2**14, r=8, p=1, dklen=32)


class AuthError(PermissionError):
    pass


def hash_password(password: str) -> str:
    salt = secrets.token_bytes(16)
    digest = hashlib.scrypt(password.encode(), salt=salt, **_SCRYPT)
    return f"scrypt${salt.hex()}${digest.hex()}"


def verify_password(password: str, stored: str) -> bool:
    try:
        _, salt_hex, digest_hex = stored.split("$")
    except ValueError:
        return False
    digest = hashlib.scrypt(password.encode(), salt=bytes.fromhex(salt_hex), **_SCRYPT)
    return hmac.compare_digest(digest.hex(), digest_hex)


def _token_hash(token: str) -> str:
    return hashlib.sha256(token.encode()).hexdigest()


def invite_code() -> str | None:
    return os.getenv("STUDY_ADMIN_KEY") or None


def any_faculty() -> bool:
    with db.session() as s:
        return bool(s.scalar(select(func.count()).select_from(Faculty)))


def register(name: str, email: str, password: str, invite: str | None, department: str = "") -> Faculty:
    expected = invite_code()
    if expected and not hmac.compare_digest(invite or "", expected):
        raise AuthError("Wrong university invite code.")
    if len(password) < 8:
        raise ValueError("Password must be at least 8 characters.")
    email = email.strip().lower()
    with db.session() as s:
        if s.scalar(select(Faculty).where(Faculty.email == email)):
            raise ValueError("An account with this email already exists.")
        f = Faculty(name=name.strip(), email=email, password_hash=hash_password(password), department=department)
        s.add(f)
        s.commit()
        return f


def login(email: str, password: str) -> tuple[str, Faculty]:
    with db.session() as s:
        f = s.scalar(select(Faculty).where(Faculty.email == email.strip().lower()))
        # Same error either way, so the response doesn't reveal which emails have accounts.
        if f is None or not verify_password(password, f.password_hash):
            raise AuthError("Wrong email or password.")
        token = secrets.token_urlsafe(32)
        now = datetime.now(timezone.utc)
        s.execute(delete(FacultyToken).where(FacultyToken.faculty_id == f.id, FacultyToken.expires_at < now))
        s.add(FacultyToken(faculty_id=f.id, token_hash=_token_hash(token), expires_at=now + timedelta(days=TOKEN_DAYS)))
        s.commit()
        return token, f


def faculty_for_token(token: str) -> Faculty | None:
    with db.session() as s:
        row = s.scalar(select(FacultyToken).where(FacultyToken.token_hash == _token_hash(token)))
        if row is None:
            return None
        expires = row.expires_at if row.expires_at.tzinfo else row.expires_at.replace(tzinfo=timezone.utc)
        if expires < datetime.now(timezone.utc):
            return None
        return s.get(Faculty, row.faculty_id)


def logout(token: str) -> None:
    with db.session() as s:
        s.execute(delete(FacultyToken).where(FacultyToken.token_hash == _token_hash(token)))
        s.commit()
