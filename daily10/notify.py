"""
Telegram reminders: one message a day per student, at the time they chose.

Setup: create a bot with @BotFather, set TELEGRAM_BOT_TOKEN, run `listen` so students can
link their account by sending "/start <student code>" to the bot, and run `run-due` every
few minutes (cron, or Celery beat in production):

    */5 * * * *  cd /path/to/Marathon && .venv/bin/python -m app.study.notify run-due

Times are in STUDY_TIMEZONE (default Asia/Kolkata). A student is reminded at most once a day.
"""

import argparse
import os
import time
from datetime import datetime
from zoneinfo import ZoneInfo

import logging
import requests

from daily10 import service

log = logging.getLogger(__name__)


API = "https://api.telegram.org/bot{token}/{method}"


def _token() -> str:
    token = os.getenv("TELEGRAM_BOT_TOKEN")
    if not token:
        raise RuntimeError("Set TELEGRAM_BOT_TOKEN (create a bot with @BotFather).")
    return token


def _call(method: str, **params) -> dict:
    r = requests.post(API.format(token=_token(), method=method), json=params, timeout=40)
    r.raise_for_status()
    return r.json()


def send(chat_id: str, text: str) -> None:
    _call("sendMessage", chat_id=chat_id, text=text)


def reminder_text(name: str, preview: dict, app_url: str) -> str:
    if preview.get("completed"):
        return ""
    parts = [f"📚 Hi {name.split()[0]}, your 10 minutes are ready."]
    if preview.get("topic"):
        parts.append(f"Today: {preview['subject']} · {preview['topic']}")
    if preview.get("reviews"):
        parts.append(f"+ {preview['reviews']} quick review question(s)")
    if not preview.get("topic") and not preview.get("reviews"):
        return ""  # nothing to study today: don't send noise
    parts.append(app_url)
    return "\n".join(parts)


def now_local() -> datetime:
    return datetime.now(ZoneInfo(os.getenv("STUDY_TIMEZONE", "Asia/Kolkata")))


def run_due(now: datetime | None = None, sender=send) -> int:
    """Send today's reminder to every student whose time has come. Returns messages sent."""
    now = now or now_local()
    today, hhmm = now.date(), now.strftime("%H:%M")
    app_url = os.getenv("STUDY_APP_URL", "http://localhost:8501/Daily_10")
    sent = 0
    for student in service.students_to_notify(hhmm, today):
        text = reminder_text(student.name, service.preview_today(student.code, today), app_url)
        try:
            if text:
                sender(student.telegram_chat_id, text)
                sent += 1
            service.mark_notified(student.id, today)
        except Exception as e:
            log.warning(f"Reminder to student {student.id} failed: {e}")
    return sent


def handle_message(chat_id: str, text: str) -> str:
    """Bot replies: /start CODE links the chat to a student; /today shows today's plan."""
    words = text.strip().split()
    if not words:
        return ""
    if words[0] == "/start":
        if len(words) < 2:
            return "Send /start followed by your student code from the Daily 10 app, e.g. /start A1B2C3"
        try:
            student = service.get_student(words[1])
        except service.NotFound:
            return "I don't recognise that code. Check it in the Daily 10 app."
        service.set_preferences(student.code, telegram_chat_id=str(chat_id))
        return f"Linked! I'll remind you daily at {student.notify_time}. Send /today to see today's plan."
    if words[0] == "/today":
        student = service.student_by_chat(str(chat_id))
        if student is None:
            return "Link your account first: /start <your student code>"
        text = reminder_text(student.name, service.preview_today(student.code), os.getenv("STUDY_APP_URL", ""))
        return text or "Nothing left for today. Nice work! ✅"
    return "Commands: /start <code>, /today"


def listen(poll_seconds: int = 30) -> None:
    """Long-poll Telegram for messages (simple; a webhook is better in production)."""
    offset = None
    while True:
        updates = _call("getUpdates", timeout=poll_seconds, offset=offset).get("result", [])
        for u in updates:
            offset = u["update_id"] + 1
            msg = u.get("message") or {}
            if "text" in msg:
                reply = handle_message(str(msg["chat"]["id"]), msg["text"])
                if reply:
                    send(str(msg["chat"]["id"]), reply)
        if not updates:
            time.sleep(1)


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    parser = argparse.ArgumentParser(description="Daily 10 Telegram reminders")
    parser.add_argument("command", choices=["run-due", "listen"])
    args = parser.parse_args()
    if args.command == "run-due":
        print(f"Sent {run_due()} reminder(s).")
    else:
        print("Listening for /start messages (Ctrl+C to stop)...")
        listen()
