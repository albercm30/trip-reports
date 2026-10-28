"""Report preview, private share links for guests, and the photo/logo file server."""
from __future__ import annotations

import secrets

from fastapi import APIRouter, Depends, Request
from fastapi.responses import RedirectResponse, Response
from sqlalchemy import select
from sqlalchemy.orm import Session

from ..config import settings
from ..db import get_db
from ..deps import NotFound, current_user, get_trip, writer
from ..models import Organization, Photo, Trip, User
from ..security import user_from_request
from ..services import storage
from ..services.reportdata import build_report
from ..web import redirect, render

router = APIRouter()


@router.get("/app/trips/{trip_id}/print")
def print_view(trip_id: str, request: Request, db: Session = Depends(get_db), user: User = Depends(current_user)):
    trip = get_trip(db, user, trip_id)
    return render(request, "report/page.html", {"trip": trip, "rorg": user.org, "print": True, "media_qs": "",
                                                "R": build_report(trip, user.org, settings.name_for(trip.report_lang))}, user=user)


@router.post("/app/trips/{trip_id}/share")
def share(trip_id: str, request: Request, db: Session = Depends(get_db), user: User = Depends(writer)):
    trip = get_trip(db, user, trip_id)
    rotate = request.query_params.get("rotate") == "1"
    if not trip.share_token or rotate:
        trip.share_token = secrets.token_urlsafe(18)
        db.commit()
    msg = "New link created. The old link no longer works." if rotate else "Share link ready. Anyone with the link can view this report."
    return redirect(f"/app/trips/{trip.id}?tab=report#share", msg)


@router.post("/app/trips/{trip_id}/unshare")
def unshare(trip_id: str, request: Request, db: Session = Depends(get_db), user: User = Depends(current_user)):
    trip = get_trip(db, user, trip_id)
    trip.share_token = None
    db.commit()
    return redirect(f"/app/trips/{trip.id}?tab=report#share", "Link turned off. Guests can no longer open it.")


@router.get("/r/{token}")
def public_report(token: str, request: Request, db: Session = Depends(get_db)):
    trip = db.scalar(select(Trip).where(Trip.share_token == token)) if len(token) > 10 else None
    if not trip:
        raise NotFound()
    org = db.get(Organization, trip.org_id)
    resp = render(request, "report/page.html", {"trip": trip, "rorg": org, "public": True, "media_qs": f"?s={token}",
                                                "R": build_report(trip, org, settings.name_for(trip.report_lang))})
    resp.headers["X-Robots-Tag"] = "noindex, nofollow"
    resp.headers["Referrer-Policy"] = "no-referrer"
    return resp


@router.get("/media/{key:path}")
def media(key: str, request: Request, db: Session = Depends(get_db)):
    org_id = key.split("/", 1)[0]
    allowed = False
    user = user_from_request(db, request)
    if user and user.org_id == org_id:
        allowed = True
    else:
        token = request.query_params.get("s", "")
        if token:
            trip = db.scalar(select(Trip).where(Trip.share_token == token))
            if trip and trip.org_id == org_id:
                org = db.get(Organization, org_id)
                if org and org.logo_key == key:
                    allowed = True
                else:
                    ph = db.scalar(select(Photo).where(Photo.storage_key == key))
                    allowed = bool(ph and ph.day.trip_id == trip.id)
    if not allowed:
        raise NotFound()
    st = storage.store()
    url = st.url(key)
    if url:
        return RedirectResponse(url, status_code=302)
    data = st.get(key)
    if data is None:
        raise NotFound()
    return Response(data, media_type="image/jpeg", headers={"Cache-Control": "private, max-age=86400"})
