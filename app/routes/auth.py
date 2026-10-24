from __future__ import annotations

import re
from datetime import datetime, timedelta, timezone

from fastapi import APIRouter, Depends, Form, Request
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from .. import plans
from ..config import settings
from ..db import get_db
from ..deps import optional_user
from ..i18n import detect_lang, translate
from ..models import Invite, Organization, PasswordReset, User, aware
from ..security import (clear_session_cookie, client_ip, create_session, end_all_sessions, end_session,
                        hash_password, login_limiter, new_token, password_problem, reset_limiter,
                        set_session_cookie, sha256, signup_limiter, verify_password)
from ..services import mail
from ..web import redirect, render

router = APIRouter()
EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")
PW_MSG = {"password_short": "Use at least 10 characters for your password.",
          "password_long": "That password is too long."}


def _safe_next(nxt: str | None) -> str:
    return nxt if nxt and nxt.startswith("/app") and not nxt.startswith("//") else "/app"


def _login_response(db: Session, user: User, request: Request, to: str, flash: str | None = None):
    token = create_session(db, user, request.headers.get("user-agent", ""))
    resp = redirect(to, flash)
    set_session_cookie(resp, token)
    return resp


def _email_taken(db: Session, email: str) -> bool:
    return db.scalar(select(func.count(User.id)).where(func.lower(User.email) == email)) > 0


# ---------------------------------------------------------------- sign up
@router.get("/signup")
def signup_form(request: Request, user=Depends(optional_user)):
    if user:
        return redirect("/app")
    return render(request, "auth/signup.html", {"form": {}})


@router.post("/signup")
def signup(request: Request, db: Session = Depends(get_db), company: str = Form(""), name: str = Form(""),
           email: str = Form(""), password: str = Form(""), agree: str = Form("")):
    email = email.strip().lower()
    form = {"company": company, "name": name, "email": email}
    err = None
    if not signup_limiter.hit(client_ip(request)):
        err = "Too many sign-ups from this connection. Try again later."
    elif not company.strip() or not name.strip():
        err = "Enter your company and your name."
    elif not EMAIL_RE.match(email):
        err = "Enter a valid email address."
    elif password_problem(password):
        err = PW_MSG[password_problem(password)]
    elif not agree:
        err = "Please accept the terms and privacy policy."
    elif _email_taken(db, email):
        err = "There is already an account with that email. Log in instead."
    if err:
        return render(request, "auth/signup.html", {"form": form, "error": err}, status=400)
    lang = detect_lang(request)
    org = Organization(name=company.strip()[:120], report_lang=lang, plan="trial", billing_status="trialing",
                       trial_ends_at=plans.new_trial_end(settings.trial_days))
    user = User(org=org, email=email, name=name.strip()[:120], password_hash=hash_password(password), role="owner",
                ui_lang=lang)
    db.add_all([org, user])
    db.commit()
    return _login_response(db, user, request, "/app?welcome=1")


# ---------------------------------------------------------------- log in / out
@router.get("/login")
def login_form(request: Request, user=Depends(optional_user)):
    if user:
        return redirect(_safe_next(request.query_params.get("next")))
    return render(request, "auth/login.html", {"next": request.query_params.get("next", ""), "email": ""})


@router.post("/login")
def login(request: Request, db: Session = Depends(get_db), email: str = Form(""), password: str = Form(""),
          next: str = Form("")):
    email = email.strip().lower()
    key = f"{client_ip(request)}|{email}"
    if not login_limiter.hit(key):
        return render(request, "auth/login.html", {"error": "Too many attempts. Wait 15 minutes and try again.",
                                                   "email": email, "next": next}, status=429)
    user = db.scalar(select(User).where(func.lower(User.email) == email))
    if not user or not user.is_active or not verify_password(password, user.password_hash):
        return render(request, "auth/login.html", {"error": "Wrong email or password.", "email": email, "next": next},
                      status=400)
    login_limiter.reset(key)
    return _login_response(db, user, request, _safe_next(next))


@router.post("/logout")
def logout(request: Request, db: Session = Depends(get_db)):
    end_session(db, request)
    resp = redirect("/login", "You've logged out.")
    clear_session_cookie(resp)
    return resp


# ---------------------------------------------------------------- password reset
@router.get("/forgot")
def forgot_form(request: Request):
    return render(request, "auth/forgot.html", {})


@router.post("/forgot")
def forgot(request: Request, db: Session = Depends(get_db), email: str = Form("")):
    email = email.strip().lower()
    shown_link = None
    if reset_limiter.hit(client_ip(request)):
        user = db.scalar(select(User).where(func.lower(User.email) == email, User.is_active.is_(True)))
        if user:
            token = new_token()
            db.add(PasswordReset(token_hash=sha256(token), user_id=user.id,
                                 expires_at=datetime.now(timezone.utc) + timedelta(hours=2)))
            db.commit()
            link = f"{settings.app_url}/reset/{token}"
            lang = user.ui_lang
            sent = mail.send(user.email, translate(lang, "Reset your {app} password", app=settings.app_name),
                             translate(lang, "Use this link to choose a new password. It works for 2 hours:\n\n{link}\n\n"
                                             "If you didn't ask for this, ignore this email.", link=link))
            if not sent and not settings.is_production:
                shown_link = link  # development only: no email server, show the link
    return render(request, "auth/forgot.html", {"sent": True, "dev_link": shown_link})


def _valid_reset(db: Session, token: str) -> PasswordReset | None:
    r = db.get(PasswordReset, sha256(token))
    if not r or r.used_at or aware(r.expires_at) < datetime.now(timezone.utc):
        return None
    return r


@router.get("/reset/{token}")
def reset_form(token: str, request: Request, db: Session = Depends(get_db)):
    return render(request, "auth/reset.html", {"token": token, "invalid": _valid_reset(db, token) is None})


@router.post("/reset/{token}")
def reset(token: str, request: Request, db: Session = Depends(get_db), password: str = Form("")):
    r = _valid_reset(db, token)
    if not r:
        return render(request, "auth/reset.html", {"token": token, "invalid": True}, status=400)
    if password_problem(password):
        return render(request, "auth/reset.html", {"token": token, "error": PW_MSG[password_problem(password)]},
                      status=400)
    user = db.get(User, r.user_id)
    user.password_hash = hash_password(password)
    r.used_at = datetime.now(timezone.utc)
    db.commit()
    end_all_sessions(db, user)
    return _login_response(db, user, request, "/app", "Your password has been changed.")


# ---------------------------------------------------------------- team invites
def _valid_invite(db: Session, token: str) -> Invite | None:
    inv = db.scalar(select(Invite).where(Invite.token_hash == sha256(token)))
    if not inv or inv.used_at or aware(inv.expires_at) < datetime.now(timezone.utc):
        return None
    return inv


@router.get("/invite/{token}")
def invite_form(token: str, request: Request, db: Session = Depends(get_db)):
    inv = _valid_invite(db, token)
    org = db.get(Organization, inv.org_id) if inv else None
    return render(request, "auth/invite.html", {"token": token, "inv": inv, "iorg": org,
                                                "form": {"email": inv.email if inv else ""}})


@router.post("/invite/{token}")
def accept_invite(token: str, request: Request, db: Session = Depends(get_db), name: str = Form(""),
                  email: str = Form(""), password: str = Form("")):
    inv = _valid_invite(db, token)
    if not inv:
        return render(request, "auth/invite.html", {"token": token, "inv": None}, status=400)
    org = db.get(Organization, inv.org_id)
    email = email.strip().lower()
    form = {"name": name, "email": email}
    err = None
    if not name.strip():
        err = "Enter your name."
    elif not EMAIL_RE.match(email):
        err = "Enter a valid email address."
    elif password_problem(password):
        err = PW_MSG[password_problem(password)]
    elif _email_taken(db, email):
        err = "There is already an account with that email. Ask the owner to invite a different email, or log in."
    elif plans.seats_used(db, org) >= plans.plan_of(org)["seats"]:
        err = "This team has no free seats on its plan. Ask the owner to upgrade."
    if err:
        return render(request, "auth/invite.html", {"token": token, "inv": inv, "iorg": org, "form": form, "error": err},
                      status=400)
    user = User(org_id=org.id, email=email, name=name.strip()[:120], password_hash=hash_password(password),
                role=inv.role if inv.role in ("guide", "owner") else "guide", ui_lang=detect_lang(request))
    inv.used_at = datetime.now(timezone.utc)
    db.add(user)
    db.commit()
    return _login_response(db, user, request, "/app", translate(user.ui_lang, "Welcome to {org}.", org=org.name))
