"""
How API requests prove who they are.

Browser (the web app / installed PWA): the session token lives in an httpOnly cookie, so page
JavaScript (and any injected script) can never read it. Cookies are Secure in production and
SameSite=Lax; on top of that, every state-changing request authenticated by cookie must carry
"X-Requested-With: daily10", a header other sites can't add to a cross-site request (CSRF).

Other clients (a native app later, the MCP server, scripts): "Authorization: Bearer <token>".
They ask for the token in the login response with "return_token": true.

    STUDENT_COOKIE  a student's device session (student_auth)
    FACULTY_COOKIE  a faculty login (auth)

When a cookie's session has expired, the 401 response also deletes the cookie, so the browser
doesn't keep sending a dead session (and the web app's middleware sends the user to log in).
"""

import os

from fastapi import HTTPException, Request, Response

from daily10 import config

STUDENT_COOKIE = "d10_session"
FACULTY_COOKIE = "d10_faculty"
CSRF_HEADER = "x-requested-with"
CSRF_VALUE = "daily10"
SAFE_METHODS = {"GET", "HEAD", "OPTIONS"}
COOKIE_MAX_AGE = 400 * 24 * 3600      # browsers cap cookies at 400 days; the server decides real expiry


def secure_cookies() -> bool:
    """Secure (HTTPS-only) cookies in production. Local development over http:// needs them off."""
    flag = os.getenv("STUDY_COOKIE_SECURE")
    return flag == "1" if flag in ("0", "1") else config.is_production()


def set_session(response: Response, name: str, token: str) -> None:
    response.set_cookie(name, token, max_age=COOKIE_MAX_AGE, path="/", httponly=True,
                        secure=secure_cookies(), samesite="lax")


def clear_session(response: Response, name: str) -> None:
    response.delete_cookie(name, path="/", httponly=True, secure=secure_cookies(), samesite="lax")


def _expired_cookie_header(name: str) -> dict:
    flags = "; Secure" if secure_cookies() else ""
    return {"set-cookie": f"{name}=; Max-Age=0; Path=/; HttpOnly; SameSite=lax{flags}"}


def bearer(request: Request) -> str:
    h = request.headers.get("authorization") or ""
    return h[7:].strip() if h.lower().startswith("bearer ") else ""


def credential(request: Request, cookie: str) -> tuple[str, bool]:
    """(token, came_from_cookie). A Bearer header wins over the cookie."""
    token = bearer(request)
    if token:
        return token, False
    return request.cookies.get(cookie, ""), True


def check_csrf(request: Request) -> None:
    if request.method not in SAFE_METHODS and request.headers.get(CSRF_HEADER) != CSRF_VALUE:
        raise HTTPException(status_code=403, detail="Missing X-Requested-With header.")


def resolve(request: Request, cookie: str, lookup, expired_detail: str):
    """
    The user behind this request's token (via `lookup(token)`), or None if there's no token at all.
    Raises 401 (and deletes the cookie) for an unknown or expired token, 403 for cookie CSRF.
    """
    token, from_cookie = credential(request, cookie)
    if not token:
        return None
    if from_cookie:
        check_csrf(request)
    user = lookup(token)
    if user is None:
        raise HTTPException(status_code=401, detail=expired_detail,
                            headers=_expired_cookie_header(cookie) if from_cookie else None)
    return user


def client_ip(request: Request) -> str | None:
    """The caller's IP. Behind Caddy, uvicorn's --proxy-headers puts the real client IP here."""
    return request.client.host if request.client else None


def user_agent(request: Request) -> str:
    return (request.headers.get("user-agent") or "")[:200]
