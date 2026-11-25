"""Student accounts (college email + password, reset links, device sessions), Telegram linking, deployment checks."""

from datetime import datetime, timedelta, timezone

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, text, update

from daily10 import config, db, mailer, student_auth
from daily10.db import OneTimeCode
from tests.conftest import fresh_database


@pytest.fixture(autouse=True)
def clean(monkeypatch):
    fresh_database()
    monkeypatch.setenv("STUDY_STUDENT_EMAIL_DOMAINS", "uvce.ac.in")


class Inbox:
    """Fake mailer: collects password-reset links."""

    def __init__(self):
        self.mail = []

    def __call__(self, to, link):
        self.mail.append((to, link))

    @property
    def token(self):
        return self.mail[-1][1].split("token=", 1)[1]


def test_only_college_emails():
    with pytest.raises(student_auth.AuthError, match="@uvce.ac.in"):
        student_auth.register("someone@gmail.com", "a-good-password", "Asha")
    with pytest.raises(ValueError):
        student_auth.register("not-an-email", "a-good-password", "Asha")
    _, st = student_auth.register(" Asha@CSE.UVCE.ac.in ", "a-good-password", "Asha")    # subdomain ok
    assert st.email == "asha@cse.uvce.ac.in"


def test_sign_up_then_log_in_on_another_device():
    token1, student = student_auth.register("asha@uvce.ac.in", "a-good-password", "Asha", "07:30")
    assert student.notify_time == "07:30" and not student_auth.needs_profile(student)
    with pytest.raises(ValueError, match="already exists"):
        student_auth.register("ASHA@uvce.ac.in", "another-password", "Asha")
    with pytest.raises(ValueError, match="at least"):
        student_auth.register("ravi@uvce.ac.in", "short", "Ravi")
    with pytest.raises(ValueError, match="name"):
        student_auth.register("ravi@uvce.ac.in", "a-good-password", "  ")

    token2, again = student_auth.login(" Asha@UVCE.ac.in", "a-good-password")
    assert again.id == student.id and token2 != token1
    assert student_auth.student_for_token(token1).id == student_auth.student_for_token(token2).id == student.id

    student_auth.logout(token1)
    assert student_auth.student_for_token(token1) is None and student_auth.student_for_token(token2) is not None
    student_auth.logout(token2, everywhere=True)
    assert student_auth.student_for_token(token2) is None


def test_wrong_password_and_unknown_email_look_the_same():
    student_auth.register("asha@uvce.ac.in", "a-good-password", "Asha")
    with pytest.raises(student_auth.AuthError) as wrong_pw:
        student_auth.login("asha@uvce.ac.in", "not-the-password")
    with pytest.raises(student_auth.AuthError) as no_account:
        student_auth.login("nobody@uvce.ac.in", "not-the-password")
    assert str(wrong_pw.value) == str(no_account.value) == "Wrong email or password."


def test_password_guessing_is_limited():
    student_auth.register("asha@uvce.ac.in", "a-good-password", "Asha")
    for _ in range(student_auth.FAILS_PER_EMAIL):
        with pytest.raises(student_auth.AuthError):
            student_auth.login("asha@uvce.ac.in", "guess-guess")
    with pytest.raises(student_auth.RateLimited):
        student_auth.login("asha@uvce.ac.in", "a-good-password")              # locked for now, even when right


def test_forgot_password_reset_signs_out_other_devices():
    old_token, student = student_auth.register("asha@uvce.ac.in", "a-good-password", "Asha")
    inbox = Inbox()
    reply = student_auth.request_password_reset("asha@uvce.ac.in", sender=inbox)
    assert student_auth.request_password_reset("nobody@uvce.ac.in", sender=inbox) == reply   # no enumeration
    assert len(inbox.mail) == 1 and "/auth/reset?token=" in inbox.mail[0][1]

    with pytest.raises(ValueError):
        student_auth.reset_password(inbox.token, "short")
    new_token, same = student_auth.reset_password(inbox.token, "a-brand-new-password")
    assert same.id == student.id and student_auth.student_for_token(new_token)
    assert student_auth.student_for_token(old_token) is None                   # other devices signed out
    with pytest.raises(student_auth.AuthError, match="expired or was already used"):
        student_auth.reset_password(inbox.token, "yet-another-password")      # single use
    student_auth.login("asha@uvce.ac.in", "a-brand-new-password")
    with pytest.raises(student_auth.AuthError):
        student_auth.login("asha@uvce.ac.in", "a-good-password")


def test_reset_links_expire_and_requests_are_limited():
    student_auth.register("asha@uvce.ac.in", "a-good-password", "Asha")
    inbox = Inbox()
    student_auth.request_password_reset("asha@uvce.ac.in", sender=inbox)
    with db.session() as s:
        s.execute(update(OneTimeCode).values(expires_at=datetime.now(timezone.utc) - timedelta(seconds=1)))
        s.commit()
    with pytest.raises(student_auth.AuthError, match="expired"):
        student_auth.reset_password(inbox.token, "a-brand-new-password")
    for _ in range(student_auth.RESETS_PER_EMAIL - 1):
        student_auth.request_password_reset("asha@uvce.ac.in", sender=inbox)
    with pytest.raises(student_auth.RateLimited):
        student_auth.request_password_reset("asha@uvce.ac.in", sender=inbox)


def test_accounts_from_before_passwords_set_one_with_forgot_password():
    from daily10 import service

    service.register_student("Old", email="old@uvce.ac.in")                    # no password yet
    with pytest.raises(student_auth.AuthError):
        student_auth.login("old@uvce.ac.in", "anything-at-all")
    inbox = Inbox()
    student_auth.request_password_reset("old@uvce.ac.in", sender=inbox)
    student_auth.reset_password(inbox.token, "my-first-password")
    assert student_auth.login("old@uvce.ac.in", "my-first-password")[1].name == "Old"


def test_change_password_needs_the_current_one():
    _, st = student_auth.register("asha@uvce.ac.in", "a-good-password", "Asha")
    with pytest.raises(student_auth.AuthError):
        student_auth.change_password(st.id, "wrong-current", "a-brand-new-password")
    student_auth.change_password(st.id, "a-good-password", "a-brand-new-password")
    student_auth.login("asha@uvce.ac.in", "a-brand-new-password")


def test_telegram_link_codes_are_single_use_and_expire():
    _, student = student_auth.register("asha@uvce.ac.in", "a-good-password", "Asha")
    link = student_auth.telegram_link_code(student.id)
    assert student_auth.redeem_telegram_code(link).id == student.id
    assert student_auth.redeem_telegram_code(link) is None

    link = student_auth.telegram_link_code(student.id)
    with db.session() as s:
        s.execute(update(OneTimeCode).values(expires_at=datetime.now(timezone.utc) - timedelta(seconds=1)))
        s.commit()
    assert student_auth.redeem_telegram_code(link) is None


def test_api_sign_up_log_in_errors_and_telegram_link(monkeypatch):
    from daily10 import main

    monkeypatch.setenv("TELEGRAM_BOT_USERNAME", "@daily10_bot")
    client = TestClient(main.app)
    body = {"name": "Asha", "email": "asha@uvce.ac.in", "password": "a-good-password"}
    assert client.post("/study/students/auth/register", json=body | {"email": "x@gmail.com"}).status_code == 403
    assert client.post("/study/students/auth/register", json=body | {"password": "short"}).status_code == 422
    ok = client.post("/study/students/auth/register", json=body | {"return_token": True}).json()
    assert ok["student"]["email"] == "asha@uvce.ac.in" and not ok["needs_profile"]
    assert client.post("/study/students/auth/register", json=body).status_code == 422          # already exists
    assert client.post("/study/students/auth/login", json={"email": "asha@uvce.ac.in", "password": "nope-nope"}).status_code == 401
    headers = {"Authorization": f"Bearer {ok['token']}"}

    link = client.post("/study/students/me/telegram-link", headers=headers).json()
    assert link["url"] == f"https://t.me/daily10_bot?start={link['code']}"

    client.post("/study/students/auth/logout", headers=headers)
    assert client.get("/study/students/me", headers=headers).status_code == 401


def test_email_failure_is_reported_not_crashed(monkeypatch):
    from daily10 import main

    student_auth.register("asha@uvce.ac.in", "a-good-password", "Asha")

    def broken(to, link):
        raise OSError("SMTP down")
    monkeypatch.setattr(mailer, "send_password_reset", broken)
    r = TestClient(main.app).post("/study/students/auth/forgot-password", json={"email": "asha@uvce.ac.in"})
    assert r.status_code == 503


def test_dev_mode_logs_the_link_but_production_refuses(monkeypatch, caplog):
    monkeypatch.delenv("SMTP_HOST", raising=False)
    mailer.send_password_reset("asha@uvce.ac.in", "http://localhost:3000/auth/reset?token=abc")
    assert "token=abc" in caplog.text
    monkeypatch.setenv("STUDY_ENV", "production")
    with pytest.raises(RuntimeError, match="SMTP"):
        mailer.send_password_reset("asha@uvce.ac.in", "http://x/auth/reset?token=abc")


def test_production_checks(monkeypatch):
    monkeypatch.delenv("STUDY_DATABASE_URL", raising=False)
    monkeypatch.delenv("STUDY_STUDENT_EMAIL_DOMAINS", raising=False)
    assert len(config.production_problems()) == 4
    monkeypatch.setenv("STUDY_ADMIN_KEY", "k")
    monkeypatch.setenv("SMTP_HOST", "smtp.example.com")
    monkeypatch.setenv("STUDY_STUDENT_EMAIL_DOMAINS", "uvce.ac.in")
    monkeypatch.setenv("STUDY_DATABASE_URL", "postgresql+psycopg://u:p@db/daily10")
    assert config.production_problems() == []


def test_timezone_decides_today(monkeypatch):
    monkeypatch.setenv("STUDY_TIMEZONE", "Pacific/Kiritimati")   # UTC+14
    ahead = config.local_today()
    monkeypatch.setenv("STUDY_TIMEZONE", "Pacific/Pago_Pago")    # UTC-11
    assert (ahead - config.local_today()).days == 1
    monkeypatch.setenv("STUDY_APP_URL", "https://daily10.uvce.ac.in/today")
    assert config.app_url() == "https://daily10.uvce.ac.in/today"


def test_existing_database_gets_the_email_column(tmp_path):
    url = f"sqlite:///{tmp_path / 'old.sqlite'}"
    engine = create_engine(url)
    with engine.begin() as conn:  # a students table from before email sign-in
        conn.execute(text("CREATE TABLE students (id INTEGER PRIMARY KEY, code VARCHAR(16) UNIQUE, name VARCHAR(120), "
                          "notify_time VARCHAR(5), telegram_chat_id VARCHAR(32), last_notified_on DATE, created_at DATETIME)"))
        conn.execute(text("INSERT INTO students (code, name, notify_time) VALUES ('ABC123', 'Old', '19:00')"))
    engine.dispose()
    db.init(url)
    db.init(url)   # idempotent
    from daily10 import service
    assert service.student_profile("ABC123")["email"] is None
    fresh_database()
