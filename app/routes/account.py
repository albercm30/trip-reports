"""Personal account: profile, password, data export and deletion (GDPR)."""
from __future__ import annotations

import json
import logging
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, Form, Request
from fastapi.responses import Response
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from ..config import settings
from ..db import get_db
from ..deps import current_user
from ..i18n import UI_LANGS
from ..models import GuestPhoto, Photo, Trip, User
from ..security import (SESSION_COOKIE, clear_session_cookie, end_all_sessions, hash_password, password_problem,
                        verify_password)
from ..services import billing as billing_svc
from ..services import storage
from ..web import redirect, render

router = APIRouter(prefix="/app/account")
log = logging.getLogger("tripreports.account")


@router.get("")
def account(request: Request, user: User = Depends(current_user)):
    return render(request, "app/account.html", {"nav": "account"}, user=user)


@router.post("")
def save_account(request: Request, db: Session = Depends(get_db), user: User = Depends(current_user),
                 name: str = Form(""), email: str = Form(""), ui_lang: str = Form("en")):
    email = email.strip().lower()
    if email != user.email:
        from .auth import EMAIL_RE
        taken = db.scalar(select(func.count(User.id)).where(func.lower(User.email) == email, User.id != user.id))
        if not EMAIL_RE.match(email) or taken:
            return render(request, "app/account.html", {"nav": "account",
                                                        "error": "That email can't be used. It may already have an account."},
                          user=user, status=400)
        user.email = email
    user.name = name.strip()[:120] or user.name
    user.ui_lang = ui_lang if ui_lang in UI_LANGS else user.ui_lang
    db.commit()
    resp = redirect("/app/account", "Saved.")
    resp.set_cookie("lang", user.ui_lang, max_age=365 * 86400, samesite="lax", path="/")
    return resp


@router.post("/password")
def change_password(request: Request, db: Session = Depends(get_db), user: User = Depends(current_user),
                    current: str = Form(""), new: str = Form("")):
    if not verify_password(current, user.password_hash):
        return render(request, "app/account.html", {"nav": "account", "pw_error": "Your current password is wrong."},
                      user=user, status=400)
    prob = password_problem(new)
    if prob:
        return render(request, "app/account.html", {"nav": "account", "pw_error": "Use at least 10 characters for your password."},
                      user=user, status=400)
    user.password_hash = hash_password(new)
    db.commit()
    end_all_sessions(db, user, keep_token=request.cookies.get(SESSION_COOKIE))
    return redirect("/app/account", "Password changed. You've been logged out on other devices.")


@router.get("/export")
def export(db: Session = Depends(get_db), user: User = Depends(current_user)):
    """Everything stored for this organization, as JSON (photos are listed by key, not embedded)."""
    org = user.org
    trips = db.scalars(select(Trip).where(Trip.org_id == org.id)).all()
    data = {
        "exported_at": datetime.now(timezone.utc).isoformat(),
        "organization": {k: getattr(org, k) for k in ("name", "accent", "tone", "report_lang", "website", "signoff",
                                                       "targets", "plan", "data_sharing")},
        "members": [{"name": u.name, "email": u.email, "role": u.role} for u in org.users if u.is_active],
        "trips": [{
            "title": t.title, "location": t.location, "start_date": t.start_date.isoformat() if t.start_date else None,
            "guests": t.guests, "guides": t.guides, "intro": t.intro, "summary": t.summary, "demo": t.is_demo,
            "days": [{
                "date": d.date.isoformat() if d.date else None, "place": d.place, "notes": d.notes,
                "narrative": d.narrative, "approved": d.approved,
                "sightings": [{"name": s.name, "sci": s.sci, "count": s.count, "heard": s.heard, "confirmed": s.sure,
                               "highlight": s.star, "group": s.group, "gbif_key": s.taxon_key} for s in d.sightings],
                "photos": [{"caption": p.caption, "file": p.storage_key} for p in d.photos],
                "positions": [{"lat": p.lat, "lon": p.lon, "label": p.label, "at": p.at} for p in d.points],
            } for d in t.days],
            "guests": [{"email": g.email, "name": g.name, "wants_news": g.news, "signed_up": g.created_at,
                        "report_sent": g.sent_at} for g in t.guest_list],
            "guest_photos": [{"author": p.author, "shown": p.approved, "file": p.storage_key} for p in t.guest_photos],
        } for t in trips],
    }
    body = json.dumps(data, ensure_ascii=False, indent=2, default=str)
    return Response(body, media_type="application/json",
                    headers={"Content-Disposition": 'attachment; filename="trip-reports-export.json"'})


@router.post("/delete")
def delete_account(request: Request, db: Session = Depends(get_db), user: User = Depends(current_user),
                   password: str = Form(""), confirm: str = Form("")):
    if not verify_password(password, user.password_hash) or confirm.strip().upper() not in ("DELETE", "BORRAR"):
        return render(request, "app/account.html", {"nav": "account",
                                                    "del_error": "Type DELETE and your password to confirm."},
                      user=user, status=400)
    org = user.org
    if user.is_owner:
        # Owner deletes the whole organization: cancel billing, remove files, then all data.
        billing_svc.cancel_now(org)
        keys = [p.storage_key for p in db.scalars(select(Photo).where(Photo.org_id == org.id))]
        keys += [p.storage_key for p in db.scalars(select(GuestPhoto).where(GuestPhoto.org_id == org.id))]
        if org.logo_key:
            keys.append(org.logo_key)
        db.delete(org)
        db.commit()
        for k in keys:
            storage.store().delete(k)
        log.info("Organization %s deleted by its owner", org.id)
    else:
        end_all_sessions(db, user)
        db.delete(user)
        db.commit()
    resp = redirect("/", "Your account has been deleted.")
    clear_session_cookie(resp)
    return resp


