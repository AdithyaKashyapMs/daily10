"""
Rate limits for sign-in, kept in the database so they hold across server workers and restarts.

    hit("code-ip:" + ip, limit=10, minutes=15)   # raises RateLimited once the 11th arrives

Each call records an attempt under `key` and refuses it if `limit` attempts already happened in
the last `minutes`. Rows older than a day are deleted as we go.
"""

from datetime import datetime, timedelta, timezone

from sqlalchemy import delete, func, select

from daily10 import db
from daily10.db import AuthAttempt

KEEP_HOURS = 24


class RateLimited(PermissionError):
    def __init__(self, minutes: int):
        super().__init__(f"Too many attempts. Try again in {minutes} minutes.")
        self.retry_after = minutes * 60


def _now() -> datetime:
    return datetime.now(timezone.utc)


def count(key: str, minutes: int) -> int:
    with db.session() as s:
        return s.scalar(select(func.count()).select_from(AuthAttempt).where(
            AuthAttempt.key == key, AuthAttempt.created_at > _now() - timedelta(minutes=minutes)))


def record(key: str) -> None:
    now = _now()
    with db.session() as s:
        s.execute(delete(AuthAttempt).where(AuthAttempt.created_at < now - timedelta(hours=KEEP_HOURS)))
        s.add(AuthAttempt(key=key[:300], created_at=now))
        s.commit()


def check(key: str, limit: int, minutes: int) -> None:
    """Refuse if `key` already has `limit` attempts in the window (doesn't record one)."""
    if count(key, minutes) >= limit:
        raise RateLimited(minutes)


def hit(key: str, limit: int, minutes: int) -> None:
    """Check, then record this attempt."""
    check(key, limit, minutes)
    record(key)


def clear(key: str) -> None:
    with db.session() as s:
        s.execute(delete(AuthAttempt).where(AuthAttempt.key == key))
        s.commit()
