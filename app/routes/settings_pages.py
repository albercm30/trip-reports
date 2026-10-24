"""Company settings (branding, writing style, target species) and team management."""
from __future__ import annotations

import re
from datetime import datetime, timedelta, timezone

from fastapi import APIRouter, Depends, File, Form, Request, UploadFile
from sqlalchemy import select
from sqlalchemy.orm import Session

from .. import plans
from ..config import settings
from ..db import get_db
from ..deps import current_user, owner
from ..i18n import translate
from ..models import Invite, User, aware
from ..security import end_all_sessions, new_token, sha256
from ..services import ai, mail, storage
from ..services.reportdata import REPORT_LANGS
from ..web import ok_or_redirect, redirect, render

router = APIRouter(prefix="/app")
HEX = re.compile(r"^#[0-9a-fA-F]{6}$")


@router.get("/settings")
def settings_page(request: Request, user: User = Depends(current_user)):
    return render(request, "app/settings.html", {"nav": "settings", "TONES": ai.TONES, "REPORT_LANGS": REPORT_LANGS},
                  user=user)


@router.post("/settings")
async def save_settings(request: Request, db: Session = Depends(get_db), user: User = Depends(owner)):
    f = await request.form()
    org = user.org
    org.name = str(f.get("name", org.name)).strip()[:120]
    accent = str(f.get("accent", org.accent))
    org.accent = accent if HEX.match(accent) else org.accent
    tone = str(f.get("tone", org.tone))
    org.tone = tone if tone in ai.TONES else org.tone
    lang = str(f.get("report_lang", org.report_lang))
    org.report_lang = lang if lang in REPORT_LANGS else org.report_lang
    org.website = str(f.get("website", "")).strip()[:200]
    org.signoff = str(f.get("signoff", ""))[:1000]
    org.targets = str(f.get("targets", ""))[:1000]
    org.show_credit = f.get("show_credit") == "1"
    org.data_sharing = f.get("data_sharing") == "1"
    db.commit()
    return ok_or_redirect(request, "/app/settings", "Saved.")


@router.post("/settings/logo")
async def upload_logo(request: Request, db: Session = Depends(get_db), user: User = Depends(owner),
                      file: UploadFile = File(...)):
    try:
        data, _, _ = storage.process_image(await file.read(storage.MAX_UPLOAD_BYTES + 1), max_side=600, quality=90)
    except storage.BadImage:
        return redirect("/app/settings", "That file couldn't be read as an image.")
    org = user.org
    old = org.logo_key
    org.logo_key = storage.new_key(org.id, "logo")
    storage.store().put(org.logo_key, data)
    db.commit()
    if old:
        storage.store().delete(old)
    return redirect("/app/settings", "Logo updated.")


@router.post("/settings/logo/delete")
def delete_logo(request: Request, db: Session = Depends(get_db), user: User = Depends(owner)):
    org = user.org
    if org.logo_key:
        storage.store().delete(org.logo_key)
        org.logo_key = None
        db.commit()
    return redirect("/app/settings", "Logo removed.")


# ---------------------------------------------------------------- team
@router.get("/team")
def team(request: Request, db: Session = Depends(get_db), user: User = Depends(current_user)):
    org = user.org
    members = list(db.scalars(select(User).where(User.org_id == org.id, User.is_active.is_(True)).order_by(User.created_at)))
    now = datetime.now(timezone.utc)
    invites = [i for i in db.scalars(select(Invite).where(Invite.org_id == org.id, Invite.used_at.is_(None)))
               if aware(i.expires_at) > now]
    new_link = request.cookies.get("invite_link")
    resp = render(request, "app/team.html", {"nav": "team", "members": members, "invites": invites,
                                             "seats": plans.plan_of(org)["seats"], "used": len(members),
                                             "new_link": new_link}, user=user)
    if new_link:
        resp.delete_cookie("invite_link", path="/app/team")
    return resp


@router.post("/team/invite")
def invite(request: Request, db: Session = Depends(get_db), user: User = Depends(owner), email: str = Form("")):
    org = user.org
    if plans.seats_used(db, org) >= plans.plan_of(org)["seats"]:
        return redirect("/app/team", "Your plan has no free seats. Upgrade to add more guides.")
    token = new_token()
    email = email.strip().lower()[:254]
    db.add(Invite(org_id=org.id, token_hash=sha256(token), email=email, role="guide",
                  expires_at=datetime.now(timezone.utc) + timedelta(days=7)))
    db.commit()
    link = f"{settings.app_url}/invite/{token}"
    if email:
        mail.send(email, translate(user.ui_lang, "{who} invited you to {org} on {app}", who=user.name or user.email,
                                   org=org.name, app=settings.app_name),
                  translate(user.ui_lang, "Join the team to write trip reports together. This link works for 7 days:\n\n{link}",
                            link=link))
    resp = redirect("/app/team", "Invite link created. Send it to your guide; it works for 7 days.")
    resp.set_cookie("invite_link", link, max_age=120, httponly=True, samesite="lax", path="/app/team",
                    secure=settings.is_production)
    return resp


@router.post("/team/invites/{inv_id}/revoke")
def revoke_invite(inv_id: str, request: Request, db: Session = Depends(get_db), user: User = Depends(owner)):
    inv = db.get(Invite, inv_id)
    if inv and inv.org_id == user.org_id:
        db.delete(inv)
        db.commit()
    return redirect("/app/team", "Invite cancelled.")


@router.post("/team/{uid}/remove")
def remove_member(uid: str, request: Request, db: Session = Depends(get_db), user: User = Depends(owner)):
    m = db.get(User, uid)
    if not m or m.org_id != user.org_id or m.id == user.id:
        return redirect("/app/team")
    end_all_sessions(db, m)
    db.delete(m)
    db.commit()
    return redirect("/app/team", "Removed from the team.")
