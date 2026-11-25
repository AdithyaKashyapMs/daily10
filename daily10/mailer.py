"""
Sending password-reset links by email (SMTP). Works with any provider: the college's own mail server,
Google Workspace, Amazon SES, Brevo, Resend, Postmark... Settings:

    SMTP_HOST, SMTP_PORT (587 = STARTTLS, 465 = SSL), SMTP_USER, SMTP_PASSWORD,
    SMTP_FROM  e.g. "Daily 10 <daily10@college.edu>"

Without SMTP_HOST (local development), the link is written to the backend's log instead.
In production (STUDY_ENV=production) that is refused: the app won't start without SMTP.
"""

import logging
import os
import smtplib
import ssl
from email.message import EmailMessage

from daily10 import config

log = logging.getLogger(__name__)


def send_password_reset(email: str, link: str) -> None:
    from daily10.student_auth import RESET_MINUTES

    send(email, "Reset your Daily 10 password",
         f"Someone (hopefully you) asked to reset the password for your Daily 10 account.\n\n"
         f"Set a new password here (the link works once, for {RESET_MINUTES} minutes):\n{link}\n\n"
         f"If you didn't ask for this, ignore this email: your password stays the same.\n",
         dev_note=f"password-reset link for {email}: {link}")


def send(to: str, subject: str, body: str, dev_note: str = "") -> None:
    host = os.getenv("SMTP_HOST")
    if not host:
        if config.is_production():
            raise RuntimeError("Email isn't set up (SMTP_HOST).")
        log.warning("DEV (no SMTP_HOST): %s", dev_note or subject)
        return

    msg = EmailMessage()
    msg["From"] = os.getenv("SMTP_FROM") or os.getenv("SMTP_USER") or f"daily10@{host}"
    msg["To"] = to
    msg["Subject"] = subject
    msg.set_content(body)
    port = int(os.getenv("SMTP_PORT", "587"))
    user, password = os.getenv("SMTP_USER"), os.getenv("SMTP_PASSWORD")
    context = ssl.create_default_context()
    if port == 465:
        server = smtplib.SMTP_SSL(host, port, context=context, timeout=20)
    else:
        server = smtplib.SMTP(host, port, timeout=20)
        server.ehlo()
        if server.has_extn("starttls"):
            server.starttls(context=context)
            server.ehlo()
        elif user:  # never send a password unencrypted; a plain relay is fine only without login
            server.quit()
            raise RuntimeError(f"{host}:{port} doesn't offer TLS; refusing to send SMTP_PASSWORD unencrypted.")
    with server:
        if user:
            server.login(user, password or "")
        server.send_message(msg)
