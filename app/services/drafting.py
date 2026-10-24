"""One place that decides how to draft: Claude when it is configured and the plan has AI left,
otherwise the free drafter. Callers get the text plus which engine wrote it."""
from __future__ import annotations

import logging

from sqlalchemy.orm import Session

from .. import plans
from ..config import settings
from ..models import AIUsage, Day, Organization, Sighting, Trip, User
from . import ai, freedraft, insights as ins, species as sp, taxonomy
from .reportdata import build_tally, group_key, group_label

log = logging.getLogger("tripreports.drafting")


def _use_ai(db: Session, org: Organization) -> bool:
    return settings.ai_enabled and plans.ai_left(db, org) > 0


def _record(db: Session, org: Organization, user: User | None, kind: str, i: int, o: int) -> None:
    db.add(AIUsage(org_id=org.id, user_id=user.id if user else None, kind=kind, input_tokens=i, output_tokens=o))


def _context(trip: Trip, org: Organization) -> str:
    return f"Trip: {trip.title or '(untitled)'}\nArea: {trip.location or '(not given)'}\nOperator: {org.name or '(not given)'}"


def species_lines(day: Day) -> str:
    out = []
    for s in day.sightings:
        line = f"- {s.name}"
        if s.sci:
            line += f" ({s.sci})"
        if s.count:
            line += f" x{s.count}"
        if s.heard:
            line += " [heard only]"
        if not s.sure:
            line += " [UNCONFIRMED]"
        out.append(line)
    return "\n".join(out)


def add_species_from_text(db: Session, org: Organization, user: User | None, trip: Trip, day: Day, raw: str) -> dict:
    """Parse a rough tally into sightings on the day. Returns {'added', 'engine', 'error'}."""
    engine, error, rows = "free", None, None
    if _use_ai(db, org):
        try:
            data, i, o = ai.parse_species(raw, org.report_lang, _context(trip, org))
            rows = sp.clean_ai_rows(data)
            _record(db, org, user, "species", i, o)
            engine = "ai"
        except ai.AIError as e:
            error = e.code
            log.info("AI species parse failed (%s), using free parser", e.code)
    if rows is None:
        rows = sp.parse_tally(raw)
    rows = taxonomy.check_rows(rows)
    existing = {(s.sci or s.name).strip().lower(): s for s in day.sightings}
    pos = len(day.sightings)
    added = 0
    for r in rows:
        group = r.get("group", "")
        if r.get("_class"):
            group = taxonomy.GROUP_BY_CLASS.get(r["_class"], group or "other")
        group = group_label(group_key(group), org.report_lang) if group else ""
        key = (r["sci"] or r["name"]).strip().lower()
        prev = existing.get(key) or existing.get(r["name"].strip().lower())
        if prev:
            if r["count"] and (not prev.count or r["count"] > prev.count):
                prev.count = r["count"]
            prev.star = prev.star or r["star"]
            continue
        s = Sighting(day=day, position=pos, name=r["name"], sci=r["sci"], count=r["count"], heard=r["heard"],
                     sure=r["sure"], star=r["star"], group=group, taxon_key=r.get("taxon_key"),
                     taxon_status=r.get("taxon_status", "unchecked"))
        db.add(s)
        existing[key] = s
        pos += 1
        added += 1
    day.raw_tally = ""
    day.approved = False
    db.commit()
    return {"added": added, "engine": engine, "error": error}


def draft_day(db: Session, org: Organization, user: User | None, trip: Trip, day: Day) -> dict:
    n = trip.days.index(day) + 1
    if _use_ai(db, org):
        try:
            text, i, o = ai.draft_day(n=n, date_s=day.date.isoformat() if day.date else "", place=day.place,
                                      notes=day.notes, species_lines=species_lines(day), lang=org.report_lang,
                                      tone=org.tone, context=_context(trip, org))
            _record(db, org, user, "day", i, o)
            day.narrative, day.approved = text.strip(), False
            db.commit()
            return {"engine": "ai", "error": None}
        except ai.AIError as e:
            err = e.code
    else:
        err = None
    day.narrative = freedraft.day_draft(n, day.place, day.notes, list(day.sightings), org.report_lang)
    day.approved = False
    db.commit()
    return {"engine": "free", "error": err}


def draft_intro(db: Session, org: Organization, user: User | None, trip: Trip) -> dict:
    rows = build_tally(trip)
    err = None
    if _use_ai(db, org):
        days_text = "\n\n".join(f"Day {i}{' (' + d.place + ')' if d.place else ''}:\n{(d.narrative or d.notes)[:2500]}"
                                for i, d in enumerate(trip.days, 1))
        try:
            d, i, o = ai.draft_intro(days_text=days_text, n_days=len(trip.days), n_species=len(rows),
                                     guests=trip.guests, lang=org.report_lang, tone=org.tone,
                                     context=_context(trip, org))
            _record(db, org, user, "intro", i, o)
            trip.intro, trip.summary = d["intro"].strip(), str(d.get("summary", "")).strip()
            db.commit()
            return {"engine": "ai", "error": None}
        except ai.AIError as e:
            err = e.code
    trip.intro, trip.summary = freedraft.intro_summary(trip.title, trip.location, len(trip.days),
                                                       [r.name for r in rows if r.star and not r.unsure],
                                                       len(rows), org.report_lang)
    db.commit()
    return {"engine": "free", "error": err}


def draft_season(db: Session, org: Organization, user: User | None, data: "ins.Insights") -> dict:
    facts = ins.facts_for_ai(data, org)
    if _use_ai(db, org):
        try:
            text, i, o = ai.draft_season(facts, org.report_lang, org.tone)
            _record(db, org, user, "season", i, o)
            db.commit()
            return {"engine": "ai", "text": text.strip(), "error": None}
        except ai.AIError as e:
            return {"engine": "free", "text": ins.free_season_text(data, org), "error": e.code}
    return {"engine": "free", "text": ins.free_season_text(data, org), "error": None}
