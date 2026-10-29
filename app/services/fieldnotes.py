"""What the guide captures on the water, often without coverage: voice notes and GPS positions.
The phone keeps them and sends them when it's back online; these helpers file them on the right day."""
from __future__ import annotations

import math
from datetime import date, datetime, timezone

from sqlalchemy import select
from sqlalchemy.orm import Session

from ..models import Day, Point, Trip, User


def parse_when(v) -> datetime | None:
    """The phone sends its wall-clock time (no zone): it's stored as is, so 10:37 on the boat shows as 10:37."""
    try:
        dt = datetime.fromisoformat(str(v).replace("Z", "+00:00"))
    except (TypeError, ValueError):
        return None
    return dt.replace(tzinfo=timezone.utc) if dt.tzinfo is None else dt


def day_for(db: Session, user: User, when: date, create) -> Day | None:
    """The company's day on that date (latest trip first). Single-day companies get a new outing if
    there isn't one yet (`create` makes it); multi-day trips are never guessed."""
    day = db.scalar(select(Day).join(Trip).where(Trip.org_id == user.org_id, Trip.is_demo.is_(False), Day.date == when)
                    .order_by(Trip.created_at.desc()).limit(1))
    if day is None and user.org.single_day:
        day = create(when).days[0]
    return day


def add_point(db: Session, day: Day, data: dict) -> Point | None:
    try:
        lat, lon = float(data.get("lat")), float(data.get("lon"))
    except (TypeError, ValueError):
        return None
    if not (math.isfinite(lat) and math.isfinite(lon) and -90 <= lat <= 90 and -180 <= lon <= 180):
        return None
    cid = str(data.get("id") or "")[:40] or None
    if cid:
        dup = db.scalar(select(Point).where(Point.day_id == day.id, Point.client_id == cid))
        if dup:
            return dup
    if len(day.points) >= 300:
        return None
    acc = data.get("acc")
    p = Point(day=day, lat=round(lat, 6), lon=round(lon, 6), label=" ".join(str(data.get("label") or "").split())[:120],
              accuracy=int(acc) if isinstance(acc, (int, float)) and math.isfinite(acc) and 0 <= acc < 1e6 else None,
              at=parse_when(data.get("at")) or datetime.now(timezone.utc), client_id=cid)
    db.add(p)
    db.commit()
    return p


def point_json(p: Point) -> dict:
    return {"id": p.id, "lat": p.lat, "lon": p.lon, "label": p.label,
            "at": p.at.isoformat() if p.at else None, "acc": p.accuracy}


def append_notes(day: Day, text: str) -> None:
    text = text.strip()
    if text:
        day.notes = (day.notes.rstrip() + "\n" + text if day.notes.strip() else text)[:20000]


def vocabulary(trip: Trip, day: Day) -> list[str]:
    words = [s.name for s in day.sightings]
    words += [w.strip() for w in (trip.org.targets or "").replace("\n", ",").split(",")]
    return [w for w in words if w]
