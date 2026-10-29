from __future__ import annotations

from datetime import datetime, timezone

from fastapi import APIRouter, Depends, File, Request, UploadFile
from fastapi.responses import JSONResponse
from sqlalchemy import select
from sqlalchemy.orm import Session, selectinload

from .. import plans
from ..db import get_db
from ..deps import current_user, writer
from ..i18n import translate
from ..models import AIUsage, Day, Trip, User
from ..services import demo, demo_marine, drafting, fieldnotes, voice
from ..services import guests as guests_svc
from ..services import insights as ins
from ..services.reportdata import build_tally
from ..web import redirect, render

router = APIRouter(prefix="/app")


def org_trips(db: Session, org_id: str) -> list[Trip]:
    return list(db.scalars(select(Trip).where(Trip.org_id == org_id)
                           .options(selectinload(Trip.days).selectinload(Day.sightings))
                           .order_by(Trip.start_date.desc().nulls_last(), Trip.updated_at.desc())))


@router.get("")
def dashboard(request: Request, db: Session = Depends(get_db), user: User = Depends(current_user)):
    trips = org_trips(db, user.org_id)
    cards = []
    for t in trips:
        approved = sum(1 for d in t.days if d.approved)
        cards.append({"trip": t, "species": len(build_tally(t)), "days": len(t.days), "approved": approved,
                      "shared": bool(t.share_token)})
    return render(request, "app/dashboard.html", {
        "cards": cards, "has_demo": any(t.is_demo for t in trips),
        "has_example": any(t.is_demo and t.intro and "La Palma" not in t.location for t in trips),
        "has_season": sum(1 for t in trips if t.is_demo and not t.intro and "La Palma" not in t.location) > 1,
        "has_marine_example": any(t.is_demo and t.intro and "La Palma" in t.location for t in trips),
        "has_marine_season": sum(1 for t in trips if t.is_demo and not t.intro and "La Palma" in t.location) > 1,
        "welcome": request.query_params.get("welcome") == "1", "nav": "trips",
        "last_real": next((t for t in trips if not t.is_demo), None),
    }, user=user)


@router.post("/demo/example")
async def demo_example(request: Request, db: Session = Depends(get_db), user: User = Depends(writer)):
    kind = (await request.form()).get("kind", "")
    if kind == "marine":
        t = demo_marine.add_marine_example(db, user.org, user.id, user.name)
        return redirect(f"/app/trips/{t.id}?tab=report", "Here's a finished example. Open the Days tab to see the rough notes it came from.")
    t = demo.add_example_trip(db, user.org, user.id, user.name)
    return redirect(f"/app/trips/{t.id}?tab=report", "Here's a finished example. Open the Days tab to see the rough notes it came from.")


@router.post("/demo/season")
async def demo_season(request: Request, db: Session = Depends(get_db), user: User = Depends(writer)):
    kind = (await request.form()).get("kind", "")
    if kind == "marine":
        n = demo_marine.add_marine_season(db, user.org, user.id, user.name)
    else:
        n = demo.add_demo_season(db, user.org, user.id, user.name)
    return redirect("/app/insights", translate(user.ui_lang, "Added {n} demo trips. You can remove them any time from Trips.", n=n))


@router.post("/demo/remove")
def demo_remove(request: Request, db: Session = Depends(get_db), user: User = Depends(current_user)):
    demo.remove_demo(db, user.org)
    return redirect("/app", "Demo trips removed.")


@router.get("/insights")
def insights(request: Request, db: Session = Depends(get_db), user: User = Depends(current_user)):
    org = user.org
    data = ins.compute(org_trips(db, org.id), org.targets)
    choices = data.species[:80]
    pick = request.query_params.get("sp")
    sel = next((s for s in choices if s.name == pick), None)
    if not sel:
        sel = next((st for _, st in data.targets if st), None) or (choices[0] if choices else None)
    return render(request, "app/insights.html", {
        "D": data, "choices": choices, "sel": sel, "nav": "insights",
        "bars": ins.month_bars(data, sel, org.report_lang) if sel else [],
        "best": ins.best_month(data, sel, org.report_lang) if sel else None,
        "lines": ins.website_lines(data, org.report_lang),
        "rare": [s for s in data.species if s.trips == 1][:40],
        "can_write": plans.can_write(org),
    }, user=user)


@router.post("/insights/season")
def season_summary(request: Request, db: Session = Depends(get_db), user: User = Depends(writer)):
    data = ins.compute(org_trips(db, user.org_id), user.org.targets)
    if data.n_trips < 2:
        return JSONResponse({"ok": False, "error": "few_trips"}, status_code=400)
    r = drafting.draft_season(db, user.org, user, data)
    return JSONResponse({"ok": True, **r})


# ---------------------------------------------------------------- field notes recorded with no outing open
def _outing_for(db: Session, user: User, when):
    from .trips import _last_trip, _new_outing
    return fieldnotes.day_for(db, user, when, lambda d: _new_outing(db, user, _last_trip(db, user.org_id), d))


@router.post("/field/points")
async def field_point(request: Request, db: Session = Depends(get_db), user: User = Depends(writer)):
    try:
        data = await request.json()
    except ValueError:
        data = {}
    when = fieldnotes.parse_when((data or {}).get("at")) if isinstance(data, dict) else None
    day = _outing_for(db, user, (when or datetime.now(timezone.utc)).date())
    if day is None:
        return JSONResponse({"ok": False, "error": "no_day"}, status_code=409)
    p = fieldnotes.add_point(db, day, data)
    if p is None:
        return JSONResponse({"ok": False, "error": "bad_point"}, status_code=400)
    return JSONResponse({"ok": True, "point": fieldnotes.point_json(p), "day": day.id, "trip": day.trip_id})


@router.post("/field/voice")
async def field_voice(request: Request, db: Session = Depends(get_db), user: User = Depends(writer),
                      audio: UploadFile = File(...)):
    f = await request.form()
    when = fieldnotes.parse_when(f.get("at")) or datetime.now(timezone.utc)
    data = await audio.read(voice.MAX_AUDIO + 1)
    day = _outing_for(db, user, when.date())
    if day is None:
        return JSONResponse({"ok": False, "error": "no_day"}, status_code=409)
    try:
        text = voice.transcribe(data, audio.content_type or "audio/webm", str(f.get("lang", ""))[:2],
                                fieldnotes.vocabulary(day.trip, day))
    except voice.VoiceError as e:
        code = 413 if str(e) == "too_large" else (400 if str(e) == "empty" else 503)
        return JSONResponse({"ok": False, "error": str(e)}, status_code=code)
    db.add(AIUsage(org_id=user.org_id, user_id=user.id, kind="voice", input_tokens=len(data) // 1000))
    fieldnotes.append_notes(day, text)
    db.commit()
    return JSONResponse({"ok": True, "text": text, "day": day.id, "trip": day.trip_id})


@router.get("/qr-card")
def qr_card(request: Request, db: Session = Depends(get_db), user: User = Depends(current_user)):
    url = guests_svc.card_url(db, user.org)
    t = guests_svc.labels(user.org.report_lang, user.org.name)
    return render(request, "app/qr.html", {"qr": guests_svc.qr_svg(url), "qr_url": url, "T": t, "card": True}, user=user)
