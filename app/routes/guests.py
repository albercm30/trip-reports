"""Public pages for guests: the QR page of an outing (leave an email for the report, upload photos)
and the company's permanent QR card, which always opens today's outing."""
from __future__ import annotations

from fastapi import APIRouter, BackgroundTasks, Depends, File, Form, Request, UploadFile
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from ..config import settings
from ..db import get_db
from ..deps import NotFound
from ..models import Guest, GuestPhoto, Organization, Trip
from ..security import RateLimiter, client_ip
from ..services import guests as gs
from ..services import storage
from ..web import redirect, render

router = APIRouter()
signup_limiter = RateLimiter(20, 60 * 60)   # per IP: a whole boat may share one mobile connection
photo_limiter = RateLimiter(15, 60 * 60)    # uploads (of up to 10 photos each) per IP


def _trip(db: Session, token: str) -> Trip:
    trip = db.scalar(select(Trip).where(Trip.guest_token == token)) if 8 <= len(token) <= 32 else None
    if not trip:
        raise NotFound()
    return trip


def _page(request: Request, trip: Trip | None, org: Organization, **ctx):
    lang = (trip.report_lang if trip else org.report_lang) or "en"
    t = gs.labels(lang, org.name or settings.name_for(lang))
    resp = render(request, "public/guest.html", {"trip": trip, "gorg": org, "T": t, "glang": lang, **ctx})
    resp.headers["X-Robots-Tag"] = "noindex, nofollow"
    resp.headers["Referrer-Policy"] = "no-referrer"
    return resp


@router.get("/q/{token}")
def boat_card(token: str, request: Request, db: Session = Depends(get_db)):
    org = db.scalar(select(Organization).where(Organization.guest_token == token)) if 8 <= len(token) <= 32 else None
    if not org:
        raise NotFound()
    trip = gs.current_trip(db, org)
    if not trip:
        return _page(request, None, org, state="none")
    return redirect(f"/g/{gs.ensure_token(db, trip)}", status=302)


@router.get("/g/{token}")
def guest_page(token: str, request: Request, db: Session = Depends(get_db)):
    trip = _trip(db, token)
    org = db.get(Organization, trip.org_id)
    q = request.query_params
    return _page(request, trip, org, state="closed" if trip.guests_closed else "open",
                 ok=q.get("ok"), photos_ok=q.get("ph"), err=q.get("err"))


@router.post("/g/{token}")
def guest_signup(token: str, request: Request, background: BackgroundTasks, db: Session = Depends(get_db),
                 email: str = Form(""), name: str = Form(""), news: str = Form(""), website: str = Form("")):
    trip = _trip(db, token)
    if trip.guests_closed:
        return redirect(f"/g/{token}")
    if website:  # hidden field: only bots fill it in
        return redirect(f"/g/{token}?ok=1#photos")
    if not signup_limiter.hit(client_ip(request)):
        return redirect(f"/g/{token}?err=slow")
    addr = gs.clean_email(email)
    if not addr:
        return redirect(f"/g/{token}?err=email")
    g = db.scalar(select(Guest).where(Guest.trip_id == trip.id, Guest.email == addr))
    if g is None:
        if db.scalar(select(func.count()).select_from(Guest).where(Guest.trip_id == trip.id)) >= gs.MAX_GUESTS:
            return redirect(f"/g/{token}?err=slow")
        g = Guest(trip_id=trip.id, org_id=trip.org_id, email=addr, lang=trip.report_lang)
        db.add(g)
    g.name = " ".join(name.split())[:80] or g.name
    g.news = g.news or news == "1"
    db.commit()
    late = bool(trip.report_sent_at and trip.share_token and not g.sent_at)
    if late:  # the report already went out: this guest gets it now
        background.add_task(gs.send_pending, trip.id)
    return redirect(f"/g/{token}?ok={'2' if late else '1'}#photos")


@router.post("/g/{token}/photos")
async def guest_photos(token: str, request: Request, db: Session = Depends(get_db),
                       files: list[UploadFile] = File(default=[]), author: str = Form("")):
    trip = _trip(db, token)
    if trip.guests_closed:
        return redirect(f"/g/{token}")
    if not photo_limiter.hit(client_ip(request)):
        return redirect(f"/g/{token}?err=slow#photos")
    files = [f for f in files if f.filename][:10]
    room = gs.MAX_GUEST_PHOTOS - len(trip.guest_photos)
    ok = 0
    for up in files[:max(0, room)]:
        try:
            data = await up.read(storage.MAX_UPLOAD_BYTES + 1)
            jpg, w, h = storage.process_image(data, max_side=1600)
        except storage.BadImage:
            continue
        key = storage.new_key(trip.org_id, "g")
        storage.store().put(key, jpg)
        db.add(GuestPhoto(trip_id=trip.id, org_id=trip.org_id, storage_key=key, width=w, height=h,
                          author=" ".join(author.split())[:80]))
        db.commit()
        ok += 1
    if files and not ok:
        return redirect(f"/g/{token}?err=photos#photos")
    return redirect(f"/g/{token}?ph={ok}#photos")
