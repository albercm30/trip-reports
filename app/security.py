"""Passwords, login sessions, CSRF protection and simple rate limiting."""
from __future__ import annotations

import base64
import hashlib
import hmac
import secrets
import time
from collections import defaultdict, deque
from datetime import datetime, timedelta, timezone

from fastapi import HTTPException, Request
from sqlalchemy.orm import Session

from .config import settings
from .models import AuthSession, User, aware

SESSION_COOKIE = "av_session"
CSRF_COOKIE = "av_csrf"
SESSION_DAYS = 30

# ---------------------------------------------------------------- passwords (scrypt, stdlib)
_N, _R, _P = 2 ** 14, 8, 1


def hash_password(password: str) -> str:
    salt = secrets.token_bytes(16)
    dk = hashlib.scrypt(password.encode(), salt=salt, n=_N, r=_R, p=_P, dklen=32)
    b = lambda x: base64.b64encode(x).decode()  # noqa: E731
    return f"scrypt${_N}${_R}${_P}${b(salt)}${b(dk)}"


def verify_password(password: str, stored: str) -> bool:
    try:
        algo, n, r, p, salt, dk = stored.split("$")
        if algo != "scrypt":
            return False
        calc = hashlib.scrypt(password.encode(), salt=base64.b64decode(salt), n=int(n), r=int(r),
                              p=int(p), dklen=len(base64.b64decode(dk)))
        return hmac.compare_digest(calc, base64.b64decode(dk))
    except (ValueError, TypeError):
        return False


def password_problem(password: str) -> str | None:
    if len(password) < 10:
        return "password_short"
    if len(password) > 200:
        return "password_long"
    return None


def sha256(s: str) -> str:
    return hashlib.sha256(s.encode()).hexdigest()


def new_token() -> str:
    return secrets.token_urlsafe(32)


# ---------------------------------------------------------------- sessions
def create_session(db: Session, user: User, user_agent: str = "") -> str:
    token = new_token()
    db.add(AuthSession(id=sha256(token), user_id=user.id, user_agent=user_agent[:200],
                       expires_at=datetime.now(timezone.utc) + timedelta(days=SESSION_DAYS)))
    user.last_login_at = datetime.now(timezone.utc)
    db.commit()
    return token


def user_from_request(db: Session, request: Request) -> User | None:
    token = request.cookies.get(SESSION_COOKIE)
    if not token:
        return None
    s = db.get(AuthSession, sha256(token))
    if not s or aware(s.expires_at) < datetime.now(timezone.utc):
        return None
    user = db.get(User, s.user_id)
    if not user or not user.is_active:
        return None
    return user


def end_session(db: Session, request: Request) -> None:
    token = request.cookies.get(SESSION_COOKIE)
    if token:
        s = db.get(AuthSession, sha256(token))
        if s:
            db.delete(s)
            db.commit()


def end_all_sessions(db: Session, user: User, keep_token: str | None = None) -> None:
    keep = sha256(keep_token) if keep_token else None
    for s in db.query(AuthSession).filter(AuthSession.user_id == user.id).all():
        if s.id != keep:
            db.delete(s)
    db.commit()


def set_session_cookie(response, token: str) -> None:
    response.set_cookie(SESSION_COOKIE, token, max_age=SESSION_DAYS * 86400, httponly=True,
                        secure=settings.is_production, samesite="lax", path="/")


def clear_session_cookie(response) -> None:
    response.delete_cookie(SESSION_COOKIE, path="/")


# ---------------------------------------------------------------- CSRF (double-submit cookie)
def csrf_token(request: Request) -> str:
    tok = getattr(request.state, "csrf", None)
    if not tok:
        tok = request.cookies.get(CSRF_COOKIE) or secrets.token_urlsafe(24)
        request.state.csrf = tok
    return tok


async def verify_csrf(request: Request) -> None:
    """Router dependency: every state-changing request must echo the CSRF cookie."""
    if request.method in ("GET", "HEAD", "OPTIONS"):
        return
    cookie = request.cookies.get(CSRF_COOKIE, "")
    sent = request.headers.get("x-csrf-token", "")
    if not sent:
        ctype = request.headers.get("content-type", "")
        if "form" in ctype:
            form = await request.form()  # cached by Starlette; route handlers can read it again
            sent = str(form.get("csrf", ""))
    if not cookie or not sent or not hmac.compare_digest(cookie, sent):
        raise HTTPException(status_code=403, detail="csrf")


# ---------------------------------------------------------------- rate limiting (per process)
class RateLimiter:
    def __init__(self, limit: int, window_s: int):
        self.limit, self.window = limit, window_s
        self.hits: dict[str, deque] = defaultdict(deque)

    def hit(self, key: str) -> bool:
        """Record an attempt. Returns False when the key is over the limit."""
        now = time.monotonic()
        q = self.hits[key]
        while q and now - q[0] > self.window:
            q.popleft()
        if len(q) >= self.limit:
            return False
        q.append(now)
        return True

    def reset(self, key: str) -> None:
        self.hits.pop(key, None)


login_limiter = RateLimiter(10, 15 * 60)
signup_limiter = RateLimiter(5, 60 * 60)
reset_limiter = RateLimiter(5, 60 * 60)
ai_limiter = RateLimiter(30, 60)


def client_ip(request: Request) -> str:
    fwd = request.headers.get("x-forwarded-for", "")
    if fwd:
        return fwd.split(",")[0].strip()
    return request.client.host if request.client else "?"
