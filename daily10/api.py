"""
Daily 10 REST API, mounted under /study.

Faculty endpoints (create subjects, upload notes and papers, generate and approve questions)
require the X-Admin-Key header when STUDY_ADMIN_KEY is set. Student endpoints use the
student's code; real sign-in (college email) is the next step before a wider rollout.
"""

import hmac
import os
import tempfile
from datetime import date

from fastapi import APIRouter, Depends, File, Form, Header, HTTPException, UploadFile
from pydantic import BaseModel, Field

from daily10 import auth, content, service

router = APIRouter(prefix="/study", tags=["Daily 10"])


def require_admin(
    authorization: str | None = Header(default=None),
    x_admin_key: str | None = Header(default=None),
) -> None:
    """
    Faculty-only endpoints accept either a faculty login token (Authorization: Bearer ...)
    or the university key (X-Admin-Key, for scripts and the CLI). On a fresh install with no
    key set and no faculty accounts yet, they are open so the first setup can happen.
    """
    key = auth.invite_code()
    if key and x_admin_key and hmac.compare_digest(x_admin_key, key):
        return
    if authorization and authorization.lower().startswith("bearer "):
        if auth.faculty_for_token(authorization[7:].strip()):
            return
        raise HTTPException(status_code=401, detail="Your session has expired. Please log in again.")
    if not key and not auth.any_faculty():
        return
    raise HTTPException(status_code=401, detail="Faculty only: please log in.")


def _not_found(e: Exception):
    raise HTTPException(status_code=404, detail=str(e))


# --- Faculty accounts ------------------------------------------------------------------------

class FacultyRegisterIn(BaseModel):
    name: str = Field(..., min_length=1, max_length=120)
    email: str = Field(..., pattern=r"^[^@\s]+@[^@\s]+\.[^@\s]+$", max_length=200)
    password: str = Field(..., min_length=8, max_length=200)
    department: str = ""
    invite_code: str | None = None


class FacultyLoginIn(BaseModel):
    email: str
    password: str


def _faculty_out(f) -> dict:
    return {"name": f.name, "email": f.email, "department": f.department}


@router.post("/faculty/register")
def faculty_register(body: FacultyRegisterIn):
    try:
        auth.register(body.name, body.email, body.password, body.invite_code, body.department)
        token, f = auth.login(body.email, body.password)
    except auth.AuthError as e:
        raise HTTPException(status_code=403, detail=str(e))
    except ValueError as e:
        raise HTTPException(status_code=409, detail=str(e))
    return {"token": token, "faculty": _faculty_out(f)}


@router.post("/faculty/login")
def faculty_login(body: FacultyLoginIn):
    try:
        token, f = auth.login(body.email, body.password)
    except auth.AuthError as e:
        raise HTTPException(status_code=401, detail=str(e))
    return {"token": token, "faculty": _faculty_out(f)}


@router.get("/faculty/me")
def faculty_me(authorization: str | None = Header(default=None)):
    f = auth.faculty_for_token(authorization[7:].strip()) if authorization and authorization.lower().startswith("bearer ") else None
    if f is None:
        raise HTTPException(status_code=401, detail="Not logged in.")
    return _faculty_out(f)


@router.post("/faculty/logout")
def faculty_logout(authorization: str | None = Header(default=None)):
    if authorization and authorization.lower().startswith("bearer "):
        auth.logout(authorization[7:].strip())
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


@router.post("/questions/{question_id}/report")
def report(question_id: int):
    try:
        service.report_question(question_id)
    except service.NotFound as e:
        _not_found(e)
    return {"ok": True}


# --- Students --------------------------------------------------------------------------------

class StudentIn(BaseModel):
    name: str = Field(..., min_length=1, max_length=120)
    notify_time: str = Field("19:00", pattern=r"^([01]\d|2[0-3]):[0-5]\d$")


@router.post("/students")
def register(body: StudentIn):
    s = service.register_student(body.name, body.notify_time)
    return {"code": s.code, "name": s.name, "notify_time": s.notify_time}


class EnrollIn(BaseModel):
    subject_code: str
    exam_date: date


@router.post("/students/{code}/enroll")
def enroll(code: str, body: EnrollIn):
    try:
        service.enroll(code, body.subject_code, body.exam_date)
    except service.NotFound as e:
        _not_found(e)
    return {"ok": True}


class PrefsIn(BaseModel):
    notify_time: str | None = Field(None, pattern=r"^([01]\d|2[0-3]):[0-5]\d$")


@router.get("/students/{code}")
def profile(code: str):
    try:
        return service.student_profile(code)
    except service.NotFound as e:
        _not_found(e)


@router.patch("/students/{code}")
def preferences(code: str, body: PrefsIn):
    try:
        service.set_preferences(code, notify_time=body.notify_time)
    except service.NotFound as e:
        _not_found(e)
    return {"ok": True}


@router.get("/students/{code}/today")
def today(code: str):
    try:
        return service.today_session(code)
    except service.NotFound as e:
        _not_found(e)


class AnswerIn(BaseModel):
    question_id: int
    chosen_index: int = Field(..., ge=0, le=3)


@router.post("/students/{code}/answers")
def answer(code: str, body: AnswerIn):
    try:
        return service.submit_answer(code, body.question_id, body.chosen_index)
    except service.NotFound as e:
        _not_found(e)


@router.get("/students/{code}/progress")
def progress(code: str):
    try:
        return service.progress(code)
    except service.NotFound as e:
        _not_found(e)
