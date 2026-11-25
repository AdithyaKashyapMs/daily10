"""Sign-in security: httpOnly cookie sessions, CSRF, rate limits, no enumeration, sliding sessions."""

from datetime import datetime, timedelta, timezone

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select, update

from daily10 import auth, db, student_auth
from daily10.db import StudentToken
from daily10.web_session import FACULTY_COOKIE, STUDENT_COOKIE
from tests.conftest import fresh_database

CSRF = {"X-Requested-With": "daily10"}


@pytest.fixture(autouse=True)
def clean(monkeypatch):
    fresh_database()
    monkeypatch.setenv("STUDY_STUDENT_EMAIL_DOMAINS", "uvce.ac.in")
    monkeypatch.delenv("STUDY_COOKIE_SECURE", raising=False)


PASSWORD = "a-good-password"


def client():
    from daily10 import main

    return TestClient(main.app)


def sign_in(c, email="asha@uvce.ac.in"):
    """Sign up the first time, log in after that."""
    r = c.post("/study/students/auth/register", json={"email": email, "name": "Asha", "password": PASSWORD})
    if r.status_code == 422 and "already exists" in r.text:
        r = c.post("/study/students/auth/login", json={"email": email, "password": PASSWORD})
    return r


# --- Cookie sessions -------------------------------------------------------------------------

def test_browser_session_is_an_httponly_cookie_and_the_token_is_never_in_the_body():
    c = client()
    r = sign_in(c)
    assert r.status_code == 200 and "token" not in r.json()
    cookie = r.headers["set-cookie"]
    assert cookie.startswith(f"{STUDENT_COOKIE}=") and "HttpOnly" in cookie and "samesite=lax" in cookie.lower()
    assert "Secure" not in cookie                                            # local http:// development
    assert c.get("/study/students/me").json()["email"] == "asha@uvce.ac.in"  # the cookie alone signs you in


def test_cookies_are_secure_in_production(monkeypatch):
    monkeypatch.setenv("STUDY_COOKIE_SECURE", "1")
    assert "Secure" in sign_in(client()).headers["set-cookie"]


def test_cookie_requests_that_change_things_need_the_csrf_header():
    c = client()
    sign_in(c)
    assert c.patch("/study/students/me", json={"notify_time": "08:00"}).status_code == 403
    assert c.patch("/study/students/me", json={"notify_time": "08:00"}, headers=CSRF).status_code == 200
    assert c.get("/study/students/me").status_code == 200                    # reads don't need it


def test_dead_cookie_is_deleted_and_logout_ends_the_session():
    c = client()
    sign_in(c)
    assert c.post("/study/students/auth/logout", headers=CSRF).status_code == 200
    assert STUDENT_COOKIE not in c.cookies
    c.cookies.set(STUDENT_COOKIE, "forged-or-expired")
    r = c.get("/study/students/me")
    assert r.status_code == 401 and f"{STUDENT_COOKIE}=;" in r.headers["set-cookie"]


def test_native_clients_can_still_use_bearer_tokens():
    c = client()
    token = c.post("/study/students/auth/register", json={"email": "asha@uvce.ac.in", "name": "Asha", "password": PASSWORD,
                                                          "return_token": True}).json()["token"]
    other = client()                                                         # no cookie
    h = {"Authorization": f"Bearer {token}"}
    assert other.patch("/study/students/me", json={"notify_time": "08:00"}, headers=h).status_code == 200  # no CSRF needed


# --- Enumeration and limits ---------------------------------------------------------------------

def test_login_and_reset_replies_dont_reveal_who_has_an_account(monkeypatch):
    from daily10 import mailer

    monkeypatch.setattr(mailer, "send_password_reset", lambda to, link: None)
    sign_in(client())
    wrong = client().post("/study/students/auth/login", json={"email": "asha@uvce.ac.in", "password": "nope-nope"})
    nobody = client().post("/study/students/auth/login", json={"email": "ravi@uvce.ac.in", "password": "nope-nope"})
    assert wrong.status_code == nobody.status_code == 401 and wrong.json() == nobody.json()
    known = client().post("/study/students/auth/forgot-password", json={"email": "asha@uvce.ac.in"}).json()
    unknown = client().post("/study/students/auth/forgot-password", json={"email": "ravi@uvce.ac.in"}).json()
    assert known == unknown


def test_one_ip_cant_guess_passwords_across_many_accounts(monkeypatch):
    monkeypatch.setattr(student_auth, "FAILS_PER_IP", 3)
    c = client()
    for i in range(3):
        c.post("/study/students/auth/login", json={"email": f"s{i}@uvce.ac.in", "password": "guess-guess"})
    r = c.post("/study/students/auth/login", json={"email": "victim@uvce.ac.in", "password": "guess-guess"})
    assert r.status_code == 429 and int(r.headers["retry-after"]) > 0


def test_one_ip_cant_mass_create_accounts(monkeypatch):
    monkeypatch.setattr(student_auth, "SIGNUPS_PER_IP", 2)
    c = client()
    for i in range(2):
        assert sign_in(c, f"s{i}@uvce.ac.in").status_code == 200
    assert sign_in(c, "s9@uvce.ac.in").status_code == 429


def test_reset_link_signs_in_through_the_api_and_change_password_needs_csrf(monkeypatch):
    from daily10 import mailer

    links = []
    monkeypatch.setattr(mailer, "send_password_reset", lambda to, link: links.append(link))
    c = client()
    sign_in(c)
    client().post("/study/students/auth/forgot-password", json={"email": "asha@uvce.ac.in"})
    token = links[-1].split("token=")[1]
    phone = client()
    r = phone.post("/study/students/auth/reset-password", json={"token": token, "password": "brand-new-password"})
    assert r.status_code == 200 and STUDENT_COOKIE in phone.cookies
    assert c.get("/study/students/me").status_code == 401                    # the old device was signed out
    assert phone.post("/study/students/auth/reset-password", json={"token": token, "password": "x" * 12}).status_code == 400

    body = {"current_password": "brand-new-password", "new_password": "third-password!"}
    assert phone.post("/study/students/me/password", json=body).status_code == 403            # no CSRF header
    assert phone.post("/study/students/me/password", json=body | {"current_password": "wrong-wrong"},
                      headers=CSRF).status_code == 403
    assert phone.post("/study/students/me/password", json=body, headers=CSRF).status_code == 200


def test_older_accounts_without_a_name_are_asked_for_one(monkeypatch):
    from daily10 import mailer, service

    links = []
    monkeypatch.setattr(mailer, "send_password_reset", lambda to, link: links.append(link))
    service.register_student("", email="old@uvce.ac.in")                       # made by the old code sign-in
    client().post("/study/students/auth/forgot-password", json={"email": "old@uvce.ac.in"})
    c = client()
    r = c.post("/study/students/auth/reset-password", json={"token": links[-1].split("token=")[1], "password": PASSWORD})
    assert r.json()["needs_profile"] is True
    assert c.patch("/study/students/me", json={"name": "   "}, headers=CSRF).status_code == 422
    assert c.patch("/study/students/me", json={"name": "Old Timer"}, headers=CSRF).status_code == 200
    assert c.get("/study/students/me").json()["needs_profile"] is False


def test_faculty_passwords_cant_be_brute_forced(monkeypatch):
    monkeypatch.setenv("STUDY_ADMIN_KEY", "uni")
    auth.register("Dr Rao", "rao@uvce.ac.in", "correct-horse-battery", "uni")
    c = client()
    for _ in range(auth.FAILS_PER_EMAIL):
        assert c.post("/study/faculty/login", json={"email": "rao@uvce.ac.in", "password": "guess-guess"}).status_code == 401
    locked = c.post("/study/faculty/login", json={"email": "rao@uvce.ac.in", "password": "correct-horse-battery"})
    assert locked.status_code == 429                                         # even the right password, for now

    monkeypatch.setattr(auth, "FAILS_PER_EMAIL", 100)
    ok = c.post("/study/faculty/login", json={"email": "rao@uvce.ac.in", "password": "correct-horse-battery"})
    assert ok.status_code == 200 and FACULTY_COOKIE in c.cookies and "token" not in ok.json()
    from daily10 import ratelimit
    assert ratelimit.count("faculty-login:rao@uvce.ac.in", 15) == 0         # success resets the count


def test_short_faculty_passwords_are_refused(monkeypatch):
    monkeypatch.setenv("STUDY_ADMIN_KEY", "uni")
    r = client().post("/study/faculty/register", json={"name": "A", "email": "a@uvce.ac.in", "password": "short1234",
                                                       "invite_code": "uni"})
    assert r.status_code == 422


# --- Sessions on phones --------------------------------------------------------------------------

def _row():
    with db.session() as s:
        return s.scalar(select(StudentToken))


def _set(**values):
    with db.session() as s:
        s.execute(update(StudentToken).values(**values))
        s.commit()


def test_sessions_slide_while_used_but_end_after_a_year():
    student = auth_student()
    token = student_auth.issue_token(student.id, "Mozilla/5.0 (iPhone)")
    assert _row().user_agent == "Mozilla/5.0 (iPhone)"
    now = datetime.now(timezone.utc)

    _set(expires_at=now + timedelta(days=3))                                  # nearly idle-expired
    assert student_auth.student_for_token(token) is not None
    assert student_auth._aware(_row().expires_at) > now + timedelta(days=student_auth.TOKEN_DAYS - 1)  # pushed out

    _set(expires_at=now - timedelta(seconds=1))                               # idle too long
    assert student_auth.student_for_token(token) is None

    _set(expires_at=now + timedelta(days=30), created_at=now - timedelta(days=student_auth.MAX_SESSION_DAYS + 1))
    assert student_auth.student_for_token(token) is None                      # absolute limit


def auth_student():
    from daily10 import service

    return service.register_student("Asha", email="asha@uvce.ac.in")


# --- Assistant --------------------------------------------------------------------------------------

def test_assistant_picks_the_role_when_a_browser_has_both_sessions(monkeypatch):
    monkeypatch.setenv("STUDY_ADMIN_KEY", "uni")
    c = client()
    sign_in(c)
    auth.register("Dr Rao", "rao@uvce.ac.in", "correct-horse-battery", "uni")
    c.post("/study/faculty/login", json={"email": "rao@uvce.ac.in", "password": "correct-horse-battery"})
    titles = lambda role: [s["title"] for s in c.get("/study/assistant/starters",
                                                      headers={"X-Daily10-Role": role}).json()]
    assert "Quiz my weak topics" in titles("student")
    assert "Weekly class report" in titles("faculty")
    assert client().get("/study/assistant/starters").status_code == 401
