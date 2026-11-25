"""
Daily 10 REST API, mounted under /study.

Faculty endpoints (create subjects, upload notes and papers, generate and approve questions)
need a faculty login (cookie or Bearer token) or the X-Admin-Key header. Student endpoints
(/students/me/...) need the session a student gets by signing in with their college email.
How sessions travel (httpOnly cookies, CSRF header, Bearer tokens): see web_session.py.
"""

import hmac
import logging
import os
import tempfile
from datetime import date

from fastapi import APIRouter, Depends, File, Form, Header, HTTPException, Request, Response, UploadFile
from pydantic import BaseModel, Field

from daily10 import auth, content, ratelimit, service, student_auth
from daily10.web_session import (
    FACULTY_COOKIE,
    STUDENT_COOKIE,
    clear_session,
    client_ip,
    credential,
    resolve,
    set_session,
    user_agent,
)

log = logging.getLogger(__name__)

router = APIRouter(prefix="/study", tags=["Daily 10"])


def require_admin(request: Request, x_admin_key: str | None = Header(default=None)) -> None:
    """
    Faculty-only endpoints accept a faculty login (cookie or Bearer token) or the university key
    (X-Admin-Key, for scripts and the CLI). On a fresh install with no key set and no faculty
    accounts yet, they are open so the first setup can happen (production refuses to start that way).
    """
    key = auth.invite_code()
    if key and x_admin_key and hmac.compare_digest(x_admin_key, key):
        return
    if resolve(request, FACULTY_COOKIE, auth.faculty_for_token, "Your session has expired. Please log in again."):
        return
    if not key and not auth.any_faculty():
        return
    raise HTTPException(status_code=401, detail="Faculty only: please log in.")


def _not_found(e: Exception):
    raise HTTPException(status_code=404, detail=str(e))


def _too_many(e: ratelimit.RateLimited):
    raise HTTPException(status_code=429, detail=str(e), headers={"retry-after": str(e.retry_after)})


# --- Faculty accounts ------------------------------------------------------------------------

class FacultyRegisterIn(BaseModel):
    name: str = Field(..., min_length=1, max_length=120)
    email: str = Field(..., pattern=r"^[^@\s]+@[^@\s]+\.[^@\s]+$", max_length=200)
    password: str = Field(..., min_length=auth.MIN_PASSWORD, max_length=200)
    department: str = Field("", max_length=64)
    invite_code: str | None = Field(None, max_length=200)
    return_token: bool = False


class FacultyLoginIn(BaseModel):
    email: str = Field(..., max_length=200)
    password: str = Field(..., max_length=200)
    return_token: bool = Field(False, description="Also return the token (MCP / scripts); browsers use the cookie")


def _faculty_out(f) -> dict:
    return {"name": f.name, "email": f.email, "department": f.department}


def _faculty_session(response: Response, token: str, f, return_token: bool) -> dict:
    set_session(response, FACULTY_COOKIE, token)
    return {"faculty": _faculty_out(f), **({"token": token} if return_token else {})}


@router.post("/faculty/register")
def faculty_register(body: FacultyRegisterIn, request: Request, response: Response):
    try:
        auth.register(body.name, body.email, body.password, body.invite_code, body.department)
        token, f = auth.login(body.email, body.password, client_ip(request))
    except ratelimit.RateLimited as e:
        _too_many(e)
    except auth.AuthError as e:
        raise HTTPException(status_code=403, detail=str(e))
    except ValueError as e:
        raise HTTPException(status_code=409, detail=str(e))
    return _faculty_session(response, token, f, body.return_token)


@router.post("/faculty/login")
def faculty_login(body: FacultyLoginIn, request: Request, response: Response):
    try:
        token, f = auth.login(body.email, body.password, client_ip(request))
    except ratelimit.RateLimited as e:
        _too_many(e)
    except auth.AuthError as e:
        raise HTTPException(status_code=401, detail=str(e))
    return _faculty_session(response, token, f, body.return_token)


@router.get("/faculty/me")
def faculty_me(request: Request):
    f = resolve(request, FACULTY_COOKIE, auth.faculty_for_token, "Your session has expired. Please log in again.")
    if f is None:
        raise HTTPException(status_code=401, detail="Not logged in.")
    return _faculty_out(f)


@router.post("/faculty/logout")
def faculty_logout(request: Request, response: Response):
    token, _ = credential(request, FACULTY_COOKIE)
    if token:
        auth.logout(token)
    clear_session(response, FACULTY_COOKIE)
    return {"ok": True}


# --- Faculty: content ------------------------------------------------------------------------

class SubjectIn(BaseModel):
    code: str = Field(..., min_length=2, max_length=32)
    name: str = Field(..., min_length=2, max_length=200)
    department: str = ""
    semester: int = 0


@router.post("/subjects", dependencies=[Depends(require_admin)])
def create_subject(body: SubjectIn):
    s = service.create_subject(body.code, body.name, body.department, body.semester)
    return {"code": s.code, "name": s.name}


@router.get("/subjects")
def subjects():
    return service.list_subjects()


async def _texts(files: list[UploadFile]) -> list[tuple[str, str]]:
    out = []
    for f in files:
        suffix = os.path.splitext(f.filename or "")[1]
        with tempfile.NamedTemporaryFile(suffix=suffix) as tmp:
            tmp.write(await f.read())
            tmp.flush()
            try:
                out.append((f.filename, content.read_file(tmp.name)))
            except ValueError as e:
                raise HTTPException(status_code=422, detail=str(e))
    return out


@router.post("/subjects/{code}/notes", dependencies=[Depends(require_admin)])
async def upload_notes(code: str, files: list[UploadFile] = File(...)):
    try:
        return {"topics_added": service.add_notes(code, await _texts(files))}
    except service.NotFound as e:
        _not_found(e)


@router.post("/subjects/{code}/past-papers", dependencies=[Depends(require_admin)])
async def upload_past_paper(code: str, file: UploadFile = File(...), year: int | None = Form(default=None)):
    (name, text), = await _texts([file])
    try:
        n = service.add_past_paper(code, text, year or content.year_from_name(name))
    except service.NotFound as e:
        _not_found(e)
    except ValueError as e:
        raise HTTPException(status_code=409, detail=str(e))
    return {"questions_found": n}


@router.post("/subjects/{code}/generate", dependencies=[Depends(require_admin)])
def generate(code: str, limit: int | None = None):
    from daily10.llm import get_json_llm

    try:
        return service.generate_questions(code, get_json_llm(), limit=limit)
    except service.NotFound as e:
        _not_found(e)


@router.post("/subjects/{code}/check", dependencies=[Depends(require_admin)])
def check(code: str):
    """Independent AI check of draft questions: flags risky ones for faculty to review first."""
    from daily10 import config
    from daily10.llm import get_json_llm

    try:
        return service.check_questions(code, get_json_llm(models=[config.JUDGE_MODEL, *config.FALLBACK_MODELS]))
    except service.NotFound as e:
        _not_found(e)


@router.get("/subjects/{code}/topics")
def topics(code: str):
    try:
        return service.topic_overview(code)
    except service.NotFound as e:
        _not_found(e)


@router.get("/subjects/{code}/questions", dependencies=[Depends(require_admin)])
def questions(code: str, status: str | None = None):
    try:
        return service.list_questions(code, status)
    except service.NotFound as e:
        _not_found(e)


class StatusIn(BaseModel):
    status: str = Field(..., pattern="^(approved|rejected|draft)$")
    reason: str = ""


@router.post("/questions/{question_id}/status", dependencies=[Depends(require_admin)])
def set_status(question_id: int, body: StatusIn):
    try:
        service.set_question_status(question_id, body.status, body.reason)
    except service.NotFound as e:
        _not_found(e)
    return {"ok": True}


class LevelIn(BaseModel):
    level: str = Field(..., pattern="^(warmup|core|exam)$")


@router.post("/questions/{question_id}/level", dependencies=[Depends(require_admin)])
def set_level(question_id: int, body: LevelIn):
    try:
        return service.set_question_level(question_id, body.level)
    except service.NotFound as e:
        _not_found(e)


@router.get("/subjects/{code}/explanations", dependencies=[Depends(require_admin)])
def explanations(code: str, status: str | None = None):
    """Topics' "explain simply" layers (plain explanation, analogy, glossary) for faculty review."""
    try:
        return service.list_explanations(code, status)
    except service.NotFound as e:
        _not_found(e)


class GlossaryIn(BaseModel):
    term: str = Field(..., min_length=1, max_length=120)
    meaning: str = Field(..., min_length=1, max_length=400)


class ExplanationIn(BaseModel):
    status: str = Field(..., pattern="^(approved|rejected|draft)$")
    simple_explanation: str | None = Field(None, max_length=2000)
    analogy: str | None = Field(None, max_length=1000)
    glossary: list[GlossaryIn] | None = Field(None, max_length=12)


@router.post("/topics/{topic_id}/explanation", dependencies=[Depends(require_admin)])
def review_explanation(topic_id: int, body: ExplanationIn):
    changes = body.model_dump(exclude={"status"}, exclude_none=True)
    try:
        return service.review_explanation(topic_id, body.status, changes)
    except service.NotFound as e:
        _not_found(e)
    except ValueError as e:
        raise HTTPException(status_code=422, detail=str(e))


# --- Students --------------------------------------------------------------------------------
# Students sign up and log in with their college email and a password (daily10/student_auth.py);
# every /students/me request carries the session from that login (cookie or Bearer token).

def current_student(request: Request) -> str:
    """The signed-in student's internal code, from the session cookie or a Bearer token."""
    student = resolve(request, STUDENT_COOKIE, student_auth.student_for_token, "Please sign in again.")
    if student is None:
        raise HTTPException(status_code=401, detail="Please sign in.")
    return student.code


TIME = r"^([01]\d|2[0-3]):[0-5]\d$"


class RegisterIn(BaseModel):
    name: str = Field(..., min_length=1, max_length=120)
    email: str = Field(..., max_length=254)
    password: str = Field(..., max_length=200)
    notify_time: str = Field("19:00", pattern=TIME)
    return_token: bool = Field(False, description="Also return the token (native apps); browsers use the cookie")


class LoginIn(BaseModel):
    email: str = Field(..., max_length=254)
    password: str = Field(..., max_length=200)
    return_token: bool = False


def _student_session(response: Response, token: str, student, return_token: bool) -> dict:
    set_session(response, STUDENT_COOKIE, token)
    return {"needs_profile": student_auth.needs_profile(student), "student": service.student_profile(student.code),
            **({"token": token} if return_token else {})}


def _auth_errors(fn, unauthorized: int = 401):
    try:
        return fn()
    except ratelimit.RateLimited as e:
        _too_many(e)
    except student_auth.AuthError as e:
        raise HTTPException(status_code=unauthorized, detail=str(e))
    except ValueError as e:
        raise HTTPException(status_code=422, detail=str(e))


@router.post("/students/auth/register")
def register(body: RegisterIn, request: Request, response: Response):
    token, student = _auth_errors(lambda: student_auth.register(
        body.email, body.password, body.name, body.notify_time, client_ip(request), user_agent(request)), 403)
    return _student_session(response, token, student, body.return_token)


@router.post("/students/auth/login")
def login(body: LoginIn, request: Request, response: Response):
    token, student = _auth_errors(lambda: student_auth.login(body.email, body.password, client_ip(request),
                                                             user_agent(request)))
    return _student_session(response, token, student, body.return_token)


class ForgotIn(BaseModel):
    email: str = Field(..., max_length=254)


@router.post("/students/auth/forgot-password")
def forgot_password(body: ForgotIn, request: Request):
    """Emails a reset link if the account exists. Same reply either way."""
    try:
        return _auth_errors(lambda: student_auth.request_password_reset(body.email, client_ip(request)), 403)
    except HTTPException:
        raise
    except Exception as e:  # SMTP failure
        log.error(f"Sending password-reset email failed: {e}")
        raise HTTPException(status_code=503, detail="Couldn't send the email. Try again in a minute.")


class ResetIn(BaseModel):
    token: str = Field(..., max_length=200)
    password: str = Field(..., max_length=200)


@router.post("/students/auth/reset-password")
def reset_password(body: ResetIn, request: Request, response: Response):
    token, student = _auth_errors(lambda: student_auth.reset_password(body.token, body.password, user_agent(request)), 400)
    return _student_session(response, token, student, False)


class PasswordIn(BaseModel):
    current_password: str = Field(..., max_length=200)
    new_password: str = Field(..., max_length=200)


@router.post("/students/me/password")
def change_password(body: PasswordIn, code: str = Depends(current_student)):
    student = service.get_student(code)
    _auth_errors(lambda: student_auth.change_password(student.id, body.current_password, body.new_password), 403)
    return {"ok": True}


class LogoutIn(BaseModel):
    everywhere: bool = False


@router.post("/students/auth/logout")
def student_logout(request: Request, response: Response, body: LogoutIn | None = None):
    token, _ = credential(request, STUDENT_COOKIE)
    if token:
        student_auth.logout(token, everywhere=bool(body and body.everywhere))
    clear_session(response, STUDENT_COOKIE)
    return {"ok": True}


class EnrollIn(BaseModel):
    subject_code: str
    exam_date: date


@router.post("/students/me/enroll")
def enroll(body: EnrollIn, code: str = Depends(current_student)):
    try:
        service.enroll(code, body.subject_code, body.exam_date)
    except service.NotFound as e:
        _not_found(e)
    return {"ok": True}


class PrefsIn(BaseModel):
    name: str | None = Field(None, min_length=1, max_length=120)
    notify_time: str | None = Field(None, pattern=r"^([01]\d|2[0-3]):[0-5]\d$")


@router.get("/students/me")
def profile(code: str = Depends(current_student)):
    return service.student_profile(code)


@router.patch("/students/me")
def preferences(body: PrefsIn, code: str = Depends(current_student)):
    name = body.name.strip() if body.name else None
    if body.name is not None and not name:
        raise HTTPException(status_code=422, detail="Enter your name.")
    service.set_preferences(code, notify_time=body.notify_time, name=name)
    return {"ok": True}


@router.post("/students/me/telegram-link")
def telegram_link(code: str = Depends(current_student)):
    """A single-use code for t.me/<bot>?start=<code>, so only this student can link their chat."""
    student = service.get_student(code)
    link = student_auth.telegram_link_code(student.id)
    bot = os.getenv("TELEGRAM_BOT_USERNAME", "").lstrip("@")
    return {"code": link, "url": f"https://t.me/{bot}?start={link}" if bot else None,
            "expires_minutes": student_auth.TELEGRAM_CODE_MINUTES}


@router.get("/students/me/today")
def today(code: str = Depends(current_student)):
    return service.today_session(code)


class AnswerIn(BaseModel):
    question_id: int
    chosen_index: int = Field(..., ge=0, le=3)


@router.post("/students/me/answers")
def answer(body: AnswerIn, code: str = Depends(current_student)):
    try:
        return service.submit_answer(code, body.question_id, body.chosen_index)
    except service.NotFound as e:
        _not_found(e)


@router.get("/students/me/progress")
def progress(code: str = Depends(current_student)):
    return service.progress(code)


@router.post("/questions/{question_id}/report")
def report(question_id: int, _student: str = Depends(current_student)):
    """A signed-in student says a question is wrong: it goes back to faculty review."""
    try:
        service.report_question(question_id)
    except service.NotFound as e:
        _not_found(e)
    return {"ok": True}
