from __future__ import annotations

import csv
import io
from datetime import date, datetime, timedelta, timezone

from fastapi import APIRouter, Depends, File, Request, UploadFile
from fastapi.responses import JSONResponse, Response
from sqlalchemy.orm import Session

from .. import plans
from ..config import settings
from ..db import get_db
from ..deps import current_user, get_day, get_trip, writer
from ..i18n import translate
from ..models import Day, Photo, Sighting, Trip, User
from ..security import ai_limiter
from ..services import verify, drafting, storage
from ..services.reportdata import REPORT_LANGS, build_report, build_tally, report_checks
from ..web import ok_or_redirect, redirect, render, wants_json

router = APIRouter(prefix="/app/trips")
TABS = ("trip", "days", "report")
ENGINE_NOTE = {
    "ai": "Drafted with AI. Read it through and fix anything that isn't right.",
    "free": "First draft ready. It's built only from your notes and sightings; edit it into your own words.",
}


def _date(v: str | None) -> date | None:
    try:
        return date.fromisoformat((v or "").strip()) if v else None
    except ValueError:
        return None


def _int(v, lo: int = 0, hi: int = 100000) -> int | None:
    try:
        n = int(str(v).strip())
    except (TypeError, ValueError):
        return None
    return max(lo, min(hi, n))


def _day_url(trip: Trip, day: Day | None = None) -> str:
    return f"/app/trips/{trip.id}?tab=days" + (f"&day={day.id}#day-{day.id}" if day else "")


def _flash_for(user: User, result: dict, base: str | None = None) -> str:
    msg = translate(user.ui_lang, ENGINE_NOTE[result["engine"]]) if base is None else translate(user.ui_lang, base)
    # When the AI can't answer, the free drafter steps in quietly: the guide just gets a draft.
    return msg


# ---------------------------------------------------------------- trips
@router.post("")
def create_trip(request: Request, db: Session = Depends(get_db), user: User = Depends(writer)):
    t = Trip(org_id=user.org_id, guides=user.name, start_date=date.today(), created_by=user.id)
    db.add(t)
    db.commit()
    return redirect(f"/app/trips/{t.id}?tab=trip&new=1")


@router.get("/{trip_id}")
def trip_page(trip_id: str, request: Request, db: Session = Depends(get_db), user: User = Depends(current_user)):
    trip = get_trip(db, user, trip_id)
    tab = request.query_params.get("tab", "trip")
    tab = tab if tab in TABS else "trip"
    org = user.org
    ctx = {"trip": trip, "tab": tab, "nav": "trips", "can_write": plans.can_write(org),
           "open_day": request.query_params.get("day"), "is_new": request.query_params.get("new") == "1",
           "ai_on": settings.ai_enabled, "REPORT_LANGS": REPORT_LANGS}
    if tab == "days":
        ctx["day_checks"] = {d.id: verify.day_problems(d, trip, i) + verify.stored_flags(d)
                             for i, d in enumerate(trip.days, 1) if d.narrative}
    if tab == "trip":
        ctx["trip_checks"] = verify.trip_text_problems(trip, len(build_tally(trip))) if (trip.intro or trip.summary) else []
    if tab == "report":
        ctx["R"] = build_report(trip, org, settings.name_for(trip.report_lang))
        ctx["checks"] = report_checks(trip)
        ctx["ready"] = not any(c[0] == "warn" for c in ctx["checks"])
        ctx["rorg"] = org
        ctx["media_qs"] = ""
    if tab == "days":
        ctx["n_species"] = len(build_tally(trip))
    return render(request, "app/trip.html", ctx, user=user)


async def _apply_trip_form(request: Request, db: Session, trip: Trip) -> None:
    f = await request.form()
    old_start = trip.start_date
    trip.title = str(f.get("title", trip.title))[:160]
    trip.location = str(f.get("location", trip.location))[:200]
    trip.guides = str(f.get("guides", trip.guides))[:200]
    if "lang" in f:
        lang = str(f.get("lang", ""))
        trip.lang = lang if lang in REPORT_LANGS else ""
    if "guests" in f:
        trip.guests = _int(f.get("guests"), 0, 999)
    if "start_date" in f:
        trip.start_date = _date(f.get("start_date"))
        if trip.start_date and trip.start_date != old_start:
            for i, d in enumerate(trip.days):
                d.date = trip.start_date + timedelta(days=i)
    if "intro" in f:
        trip.intro = str(f.get("intro", ""))[:6000]
    if "summary" in f:
        trip.summary = str(f.get("summary", ""))[:6000]
    db.commit()


@router.post("/{trip_id}")
async def save_trip(trip_id: str, request: Request, db: Session = Depends(get_db), user: User = Depends(writer)):
    trip = get_trip(db, user, trip_id)
    await _apply_trip_form(request, db, trip)
    return ok_or_redirect(request, f"/app/trips/{trip.id}?tab=trip", "Saved.")


@router.post("/{trip_id}/delete")
def delete_trip(trip_id: str, request: Request, db: Session = Depends(get_db), user: User = Depends(current_user)):
    trip = get_trip(db, user, trip_id)
    keys = [p.storage_key for d in trip.days for p in d.photos]
    db.delete(trip)
    db.commit()
    for k in keys:
        storage.store().delete(k)
    return redirect("/app", "Trip deleted.")


@router.post("/{trip_id}/intro/draft")
async def draft_intro(trip_id: str, request: Request, db: Session = Depends(get_db), user: User = Depends(writer)):
    trip = get_trip(db, user, trip_id)
    await _apply_trip_form(request, db, trip)
    if not trip.days:
        return redirect(f"/app/trips/{trip.id}?tab=trip", "Add at least one day first.")
    if not ai_limiter.hit(user.org_id):
        return redirect(f"/app/trips/{trip.id}?tab=trip", "Too many drafts at once. Wait a minute and try again.")
    r = drafting.draft_intro(db, user.org, user, trip)
    return redirect(f"/app/trips/{trip.id}?tab=trip#closing", _flash_for(user, r))


@router.get("/{trip_id}/sightings.csv")
def export_csv(trip_id: str, db: Session = Depends(get_db), user: User = Depends(current_user)):
    trip = get_trip(db, user, trip_id)
    buf = io.StringIO()
    w = csv.writer(buf)
    w.writerow(["trip", "day", "date", "place", "common_name", "scientific_name", "count", "heard_only",
                "confirmed", "highlight", "group", "gbif_taxon_key"])
    for i, d in enumerate(trip.days, 1):
        for s in d.sightings:
            w.writerow([trip.title, i, d.date.isoformat() if d.date else "", d.place, s.name, s.sci,
                        "" if s.count is None else s.count, int(s.heard), int(s.sure), int(s.star), s.group,
                        s.taxon_key or ""])
    name = "".join(c if c.isalnum() else "-" for c in (trip.title or "trip").lower()).strip("-") or "trip"
    return Response("﻿" + buf.getvalue(), media_type="text/csv; charset=utf-8",
                    headers={"Content-Disposition": f'attachment; filename="{name}-sightings.csv"'})


# ---------------------------------------------------------------- days
@router.post("/{trip_id}/days")
def add_day(trip_id: str, request: Request, db: Session = Depends(get_db), user: User = Depends(writer)):
    trip = get_trip(db, user, trip_id)
    n = len(trip.days)
    if n >= 60:
        return redirect(_day_url(trip), "A trip can have up to 60 days.")
    base = trip.start_date or date.today()
    d = Day(trip=trip, position=n, date=base + timedelta(days=n))
    db.add(d)
    db.commit()
    return redirect(_day_url(trip, d))


async def _save_day_form(request: Request, db: Session, user: User, trip: Trip, day: Day) -> None:
    """Apply the whole day form: fields, species rows and photo captions."""
    f = await request.form()
    if "place" in f:
        day.place = str(f.get("place", ""))[:200]
        day.date = _date(f.get("date")) or day.date
        day.notes = str(f.get("notes", ""))[:20000]
        day.raw_tally = str(f.get("raw_tally", ""))[:10000]
        new_narr = str(f.get("narrative", ""))[:12000]
        if new_narr.strip() != (day.narrative or "").strip():
            day.ai_flags = ""  # the guide changed the text: the fact-checker's notes no longer apply
        day.narrative = new_narr
        approved = f.get("approved") == "1"
        if approved and not day.approved:
            day.approved_by, day.approved_at = user.name or user.email, datetime.now(timezone.utc)
        day.approved = approved and bool(day.narrative.strip())
        for s in day.sightings:
            p = f"sp_{s.id}_"
            if p + "name" not in f:
                continue
            s.name = str(f.get(p + "name", ""))[:120].strip()
            new_sci = str(f.get(p + "sci", ""))[:120].strip()
            if new_sci != s.sci:
                s.sci, s.taxon_status, s.taxon_key = new_sci, "unchecked", None
            s.count = _int(f.get(p + "count")) if str(f.get(p + "count", "")).strip() else None
            s.heard = f.get(p + "heard") == "1"
            s.sure = f.get(p + "sure") == "1"
            s.star = f.get(p + "star") == "1"
        for ph in day.photos:
            k = f"ph_{ph.id}_caption"
            if k in f:
                ph.caption = str(f.get(k, ""))[:300]
    db.commit()


@router.post("/{trip_id}/days/{day_id}")
async def save_day(trip_id: str, day_id: str, request: Request, db: Session = Depends(get_db),
                   user: User = Depends(writer)):
    trip = get_trip(db, user, trip_id)
    day = get_day(db, trip, day_id)
    await _save_day_form(request, db, user, trip, day)
    if wants_json(request):
        return JSONResponse({"ok": True, "approved": day.approved})
    return redirect(_day_url(trip, day), "Saved.")


@router.post("/{trip_id}/days/{day_id}/delete")
def delete_day(trip_id: str, day_id: str, request: Request, db: Session = Depends(get_db),
               user: User = Depends(writer)):
    trip = get_trip(db, user, trip_id)
    day = get_day(db, trip, day_id)
    keys = [p.storage_key for p in day.photos]
    trip.days.remove(day)
    db.flush()
    for i, d in enumerate(trip.days):
        d.position = i
    db.commit()
    for k in keys:
        storage.store().delete(k)
    return redirect(_day_url(trip), "Day deleted.")


@router.post("/{trip_id}/days/{day_id}/species/parse")
async def parse_species(trip_id: str, day_id: str, request: Request, db: Session = Depends(get_db),
                        user: User = Depends(writer)):
    trip = get_trip(db, user, trip_id)
    day = get_day(db, trip, day_id)
    await _save_day_form(request, db, user, trip, day)
    raw = day.raw_tally.strip()
    use_notes = settings.ai_enabled and bool(day.notes.strip())
    if not raw and not use_notes:
        return redirect(_day_url(trip, day), "Paste or dictate your sightings first.")
    if not ai_limiter.hit(user.org_id):
        return redirect(_day_url(trip, day), "Too many requests at once. Wait a minute and try again.")
    r = drafting.add_species_from_text(db, user.org, user, trip, day, raw, day.notes if use_notes else "")
    unsure = sum(1 for s in day.sightings if not s.sure)
    msg = translate(user.ui_lang, "{n} added.", n=r["added"])
    if unsure:
        msg += " " + translate(user.ui_lang, "Check the {u} highlighted.", u=unsure)
    if r.get("dropped"):
        msg += " " + translate(user.ui_lang, "{n} left out because they weren't in your own words.", n=r["dropped"])
    return redirect(_day_url(trip, day), msg)


PROOF_ERRORS = {
    "unavailable": "Couldn't check the spelling right now. Try again in a minute.",
    "rate_limited": "The AI is busy right now. Try again in a minute.",
    "too_long": "This text is too long to check in one go.",
    "bad_output": "The AI's correction changed too much, so the text was left as it was.",
    "refused": "The AI couldn't check this text.",
}


def _proof_msg(user: User, r: dict) -> str:
    if r["engine"] == "ai":
        return translate(user.ui_lang, "Spelling and grammar fixed. Your facts and wording are unchanged.")
    return translate(user.ui_lang, PROOF_ERRORS.get(r.get("error") or "", "Nothing to fix."))


@router.post("/{trip_id}/days/{day_id}/proofread")
async def proofread_day(trip_id: str, day_id: str, request: Request, db: Session = Depends(get_db),
                        user: User = Depends(writer)):
    trip = get_trip(db, user, trip_id)
    day = get_day(db, trip, day_id)
    await _save_day_form(request, db, user, trip, day)
    if not ai_limiter.hit(user.org_id):
        return redirect(_day_url(trip, day), "Too many requests at once. Wait a minute and try again.")
    r = drafting.proofread(db, user.org, user, day.narrative, trip.report_lang)
    if r["engine"] == "ai" and r["text"] != day.narrative:
        day.narrative, day.approved = r["text"], False
        db.commit()
    return redirect(_day_url(trip, day).replace(f"#day-{day.id}", f"#narr-{day.id}"), _proof_msg(user, r))


@router.post("/{trip_id}/proofread")
async def proofread_trip(trip_id: str, request: Request, db: Session = Depends(get_db), user: User = Depends(writer)):
    trip = get_trip(db, user, trip_id)
    await _apply_trip_form(request, db, trip)
    if not ai_limiter.hit(user.org_id):
        return redirect(f"/app/trips/{trip.id}?tab=trip#closing", "Too many requests at once. Wait a minute and try again.")
    results = []
    for field in ("intro", "summary"):
        r = drafting.proofread(db, user.org, user, getattr(trip, field), trip.report_lang)
        if r["engine"] == "ai":
            setattr(trip, field, r["text"])
        results.append(r)
    db.commit()
    best = next((r for r in results if r["engine"] == "ai"), results[0])
    return redirect(f"/app/trips/{trip.id}?tab=trip#closing", _proof_msg(user, best))


@router.post("/{trip_id}/days/{day_id}/species/add")
async def add_species(trip_id: str, day_id: str, request: Request, db: Session = Depends(get_db),
                      user: User = Depends(writer)):
    trip = get_trip(db, user, trip_id)
    day = get_day(db, trip, day_id)
    await _save_day_form(request, db, user, trip, day)
    if len(day.sightings) >= 500:
        return redirect(_day_url(trip, day), "A day can have up to 500 species rows.")
    s = Sighting(day=day, position=len(day.sightings), name="", sure=True, heard=False, star=False)
    db.add(s)
    db.commit()
    return redirect(_day_url(trip, day) .replace(f"#day-{day.id}", f"#sp-{s.id}"))


@router.post("/{trip_id}/days/{day_id}/species/{sid}/delete")
async def delete_species(trip_id: str, day_id: str, sid: str, request: Request, db: Session = Depends(get_db),
                         user: User = Depends(writer)):
    trip = get_trip(db, user, trip_id)
    day = get_day(db, trip, day_id)
    await _save_day_form(request, db, user, trip, day)
    s = next((x for x in day.sightings if x.id == sid), None)
    if s:
        day.sightings.remove(s)
        db.commit()
    return redirect(_day_url(trip, day))


@router.post("/{trip_id}/days/{day_id}/draft")
async def draft_day(trip_id: str, day_id: str, request: Request, db: Session = Depends(get_db),
                    user: User = Depends(writer)):
    trip = get_trip(db, user, trip_id)
    day = get_day(db, trip, day_id)
    await _save_day_form(request, db, user, trip, day)
    if not day.notes.strip() and not day.sightings:
        return redirect(_day_url(trip, day), "Add some notes or sightings first.")
    if not ai_limiter.hit(user.org_id):
        return redirect(_day_url(trip, day), "Too many drafts at once. Wait a minute and try again.")
    r = drafting.draft_day(db, user.org, user, trip, day)
    return redirect(_day_url(trip, day).replace(f"#day-{day.id}", f"#narr-{day.id}"), _flash_for(user, r))


@router.post("/{trip_id}/days/{day_id}/photos")
async def upload_photos(trip_id: str, day_id: str, request: Request, db: Session = Depends(get_db),
                        user: User = Depends(writer), files: list[UploadFile] = File(default=[])):
    trip = get_trip(db, user, trip_id)
    day = get_day(db, trip, day_id)
    files = [f for f in files if f.filename][:12]
    ok = 0
    for up in files:
        if len(day.photos) >= 40:
            break
        try:
            data = await up.read(storage.MAX_UPLOAD_BYTES + 1)
            jpg, w, h = storage.process_image(data)
        except storage.BadImage:
            continue
        key = storage.new_key(user.org_id)
        storage.store().put(key, jpg)
        db.add(Photo(day=day, org_id=user.org_id, storage_key=key, width=w, height=h, position=len(day.photos)))
        db.flush()
        ok += 1
    db.commit()
    if not files:
        msg = "Choose one or more photos first."
    elif ok == len(files):
        msg = translate(user.ui_lang, "{n} photos added.", n=ok)
    else:
        msg = translate(user.ui_lang, "{ok} of {n} photos added. The others couldn't be read.", ok=ok, n=len(files))
    return redirect(_day_url(trip, day), msg)


@router.post("/{trip_id}/days/{day_id}/photos/{pid}/delete")
async def delete_photo(trip_id: str, day_id: str, pid: str, request: Request, db: Session = Depends(get_db),
                       user: User = Depends(writer)):
    trip = get_trip(db, user, trip_id)
    day = get_day(db, trip, day_id)
    await _save_day_form(request, db, user, trip, day)
    p = next((x for x in day.photos if x.id == pid), None)
    if p:
        key = p.storage_key
        day.photos.remove(p)
        db.commit()
        storage.store().delete(key)
    return redirect(_day_url(trip, day))
