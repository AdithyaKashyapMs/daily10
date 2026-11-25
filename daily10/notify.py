"""
Telegram reminders: one message a day per student, at the time they chose.

Setup: create a bot with @BotFather, set TELEGRAM_BOT_TOKEN and TELEGRAM_BOT_USERNAME, and run

    python -m daily10.notify serve        # answers the bot and sends reminders every minute

(or `listen` and `run-due` separately, e.g. run-due from cron). Students link their chat from the
app's Me tab, which opens t.me/<bot>?start=<single-use code>.

Times are in STUDY_TIMEZONE (default Asia/Kolkata). A student is reminded at most once a day.
"""

import argparse
import os
import time
import threading
from datetime import datetime

import logging
import requests

from daily10 import config, service, student_auth

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
    return config.local_now()


def run_due(now: datetime | None = None, sender=send) -> int:
    """Send today's reminder to every student whose time has come. Returns messages sent."""
    now = now or now_local()
    today, hhmm = now.date(), now.strftime("%H:%M")
    app_url = config.app_url()
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
    """Bot replies: /start <link code> links the chat to a student; /today shows today's plan."""
    words = text.strip().split()
    if not words:
        return ""
    if words[0] == "/start":
        if len(words) < 2:
            return "Open the Daily 10 app, go to Me, and tap \"Turn on Telegram reminders\" to link this chat."
        student = student_auth.redeem_telegram_code(words[1])
        if student is None:
            return "That link has expired. Open the Daily 10 app (Me tab) and tap the Telegram button again."
        service.set_preferences(student.code, telegram_chat_id=str(chat_id))
        return f"Linked! I'll remind you daily at {student.notify_time}. Send /today to see today's plan."
    if words[0] == "/today":
        student = service.student_by_chat(str(chat_id))
        if student is None:
            return "Link your account first: open the Daily 10 app, Me tab, Telegram button."
        text = reminder_text(student.name, service.preview_today(student.code, config.local_today()), config.app_url())
        return text or "Nothing left for today. Nice work! ✅"
    if words[0] == "/stop":
        student = service.student_by_chat(str(chat_id))
        if student:
            service.set_preferences(student.code, telegram_chat_id="")
        return "Reminders are off. Link again from the app any time."
    return "Commands: /today, /stop"


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


def serve(every_seconds: int = 60) -> None:
    """Answer the bot and send due reminders, in one process (what the Docker worker runs)."""
    threading.Thread(target=listen, daemon=True, name="telegram-listen").start()
    while True:
        try:
            sent = run_due()
            if sent:
                log.info(f"Sent {sent} reminder(s)")
        except Exception as e:
            log.warning(f"Reminder run failed: {e}")
        time.sleep(every_seconds)


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    parser = argparse.ArgumentParser(description="Daily 10 Telegram reminders")
    parser.add_argument("command", choices=["run-due", "listen", "serve"])
    args = parser.parse_args()
    _token()  # fail fast without TELEGRAM_BOT_TOKEN
    if args.command == "run-due":
        print(f"Sent {run_due()} reminder(s).")
    elif args.command == "listen":
        print("Listening for bot messages (Ctrl+C to stop)...")
        listen()
    else:
        print("Answering the bot and sending reminders every minute (Ctrl+C to stop)...")
        serve()
