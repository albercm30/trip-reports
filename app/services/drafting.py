"""One place that decides how to read and draft: AI when it is configured and the plan has AI left,
otherwise the free parser and drafter. Callers get the result plus which engine produced it."""
from __future__ import annotations

import logging

from sqlalchemy.orm import Session

from .. import plans
from ..config import settings
from sqlalchemy import select

from ..models import AIUsage, Day, Organization, Sighting, Trip, User
from . import ai, freedraft, insights as ins, species as sp, taxonomy, verify
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


def _org_species(db: Session, org: Organization) -> list[tuple[str, str, str]]:
    """Species this operator has confirmed before: (name, scientific name, group)."""
    rows = db.execute(select(Sighting.name, Sighting.sci, Sighting.group).join(Day).join(Trip)
                      .where(Trip.org_id == org.id, Sighting.sure.is_(True), Sighting.name != "")
                      .distinct().limit(2000)).all()
    return [(n, sci, group_key(g)) for n, sci, g in rows]


def add_species_from_text(db: Session, org: Organization, user: User | None, trip: Trip, day: Day, raw: str,
                          notes: str = "") -> dict:
    """Read the tally (and, with AI, the notes) into sightings on the day.
    Returns {'added', 'engine', 'error', 'dropped'}."""
    engine, error, rows, dropped = "free", None, None, 0
    own = _org_species(db, org)
    if _use_ai(db, org):
        try:
            known = "; ".join(sorted({f"{n} ({sci})" if sci else n for n, sci, _ in own})[:150])
            data, i, o = ai.parse_species(raw, notes, trip.report_lang, _context(trip, org), known)
            raw_rows = data.get("species") if isinstance(data, dict) else data
            rows = sp.clean_ai_rows(data, raw + "\n" + notes)
            dropped = max(0, len(raw_rows or []) - len(rows)) if isinstance(raw_rows, list) else 0
            rows, changes = verify.check_species_rows(rows, raw + "\n" + notes, sp.Vocab(own), trip.report_lang,
                                                      tally=raw)
            if changes:
                log.info("Species checks: %s", "; ".join(changes))
            _record(db, org, user, "species", i, o)
            engine = "ai"
        except ai.AIError as e:
            error = e.code
            log.info("AI species parse failed (%s), using free parser", e.code)
    if rows is None:
        rows = sp.parse_tally(raw, sp.Vocab(own), trip.report_lang)
    rows = taxonomy.check_rows(rows)
    existing = {(s.sci or s.name).strip().lower(): s for s in day.sightings}
    pos = len(day.sightings)
    added = 0
    for r in rows:
        group = r.get("group", "")
        if r.get("_class"):
            group = taxonomy.GROUP_BY_CLASS.get(r["_class"], group or "other")
        group = group_label(group_key(group), trip.report_lang) if group else ""
        key = (r["sci"] or r["name"]).strip().lower()
        prev = existing.get(key) or existing.get(r["name"].strip().lower())
        if prev:
            if r["count"] and (not prev.count or r["count"] > prev.count):
                prev.count = r["count"]
            prev.star = prev.star or r["star"]
            continue
        s = Sighting(day=day, position=pos, name=r["name"], sci=r["sci"], count=r["count"], heard=r["heard"],
                     sure=r["sure"], star=r["star"], group=group, taxon_key=r.get("taxon_key"),
                     taxon_status=r.get("taxon_status", "unchecked"), source=r.get("source", "")[:200])
        db.add(s)
        existing[key] = s
        pos += 1
        added += 1
    day.raw_tally = ""
    day.approved = False
    db.commit()
    return {"added": added, "engine": engine, "error": error, "dropped": dropped}


def checked_draft(write, check, notes: str, species_txt: str, lang: str, record=None, as_text=lambda x: x) -> dict:
    """Write with the AI, then check it twice over: plain code (species, numbers, language, certainty,
    format) and a second AI call that quotes any detail the notes don't support. If either finds
    something, the AI rewrites once, told exactly what to fix. Returns the result and what's left."""
    record = record or (lambda kind, i, o: None)
    first = write(None, None)
    problems = check(first)
    claims = []
    try:
        found, i, o = ai.unsupported_claims(as_text(first), notes, species_txt)
        record("check", i, o)
        claims = [{"kind": "claim", "what": c["quote"], "why": c["why"]} for c in found]
    except ai.AIError:
        pass
    all_first = problems + claims
    result, left = first, problems
    if all_first:
        try:
            second = write(as_text(first), verify.feedback(all_first, lang))
            p2 = check(second)
            if len(p2) <= len(problems):
                result, left = second, p2
        except ai.AIError:
            pass
    return {"result": result, "problems": left, "first_problems": all_first}


def draft_day(db: Session, org: Organization, user: User | None, trip: Trip, day: Day) -> dict:
    n = trip.days.index(day) + 1
    if _use_ai(db, org):
        try:
            lines = species_lines(day)
            kw = dict(n=n, date_s=day.date.isoformat() if day.date else "", place=day.place, notes=day.notes,
                      species_lines=lines, lang=trip.report_lang, tone=org.tone, context=_context(trip, org))

            def write(previous, problems):
                text, i, o = ai.draft_day(**kw, previous=previous or "", problems=problems or "")
                _record(db, org, user, "day", i, o)
                return text.strip()

            def check(text):
                old, day.narrative = day.narrative, text
                try:
                    return verify.day_problems(day, trip, n)
                finally:
                    day.narrative = old

            out = checked_draft(write, check, day.notes or "", lines, trip.report_lang,
                                record=lambda k, i, o: _record(db, org, user, k, i, o))
            day.narrative = verify.tidy(out["result"])
            day.approved = False
            db.commit()
            return {"engine": "ai", "error": None}
        except ai.AIError as e:
            err = e.code
    else:
        err = None
    day.narrative = freedraft.day_draft(n, day.place, day.notes, list(day.sightings), trip.report_lang)
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
            kw = dict(days_text=days_text, n_days=len(trip.days), n_species=len(rows), guests=trip.guests,
                      lang=trip.report_lang, tone=org.tone, context=_context(trip, org))

            def write(previous, problems):
                d, i, o = ai.draft_intro(**kw, previous=previous or "", problems=problems or "")
                _record(db, org, user, "intro", i, o)
                return (d["intro"].strip(), str(d.get("summary", "")).strip())

            def check(pair):
                old = (trip.intro, trip.summary)
                trip.intro, trip.summary = pair
                try:
                    return verify.trip_text_problems(trip, len(rows))
                finally:
                    trip.intro, trip.summary = old

            all_notes = "\n\n".join(d.notes or "" for d in trip.days)
            sp_txt = "\n".join(species_lines(d) for d in trip.days)
            out = checked_draft(write, check, all_notes + "\n\n" + days_text, sp_txt, trip.report_lang,
                                record=lambda k, i, o: _record(db, org, user, k, i, o),
                                as_text=lambda pair: f"{pair[0]}\n\n{pair[1]}")
            trip.intro, trip.summary = (verify.tidy(x) for x in out["result"])
            db.commit()
            return {"engine": "ai", "error": None}
        except ai.AIError as e:
            err = e.code
    all_notes = "\n".join(d.notes or "" for d in trip.days)
    trip.intro, trip.summary = freedraft.intro_summary(trip.title, trip.location, len(trip.days),
                                                       [r.name for r in rows if r.star and not r.unsure],
                                                       len(rows), freedraft.draft_lang(all_notes, trip.report_lang))
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


def proofread(db: Session, org: Organization, user: User | None, text: str, lang: str | None = None) -> dict:
    """Fix spelling, grammar and dictation errors in text the guide wrote. Needs AI."""
    if not text.strip():
        return {"text": text, "engine": "none", "error": None}
    if not _use_ai(db, org):
        return {"text": text, "engine": "none", "error": "unavailable"}
    try:
        out, i, o = ai.proofread(text, lang or org.report_lang)
        _record(db, org, user, "proofread", i, o)
        db.commit()
        return {"text": out, "engine": "ai", "error": None}
    except ai.AIError as e:
        return {"text": text, "engine": "none", "error": e.code}
