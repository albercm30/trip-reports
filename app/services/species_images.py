"""Reference photos of species for guest reports, from Wikimedia Commons.

Only freely licensed images are used (CC0, public domain, CC BY, CC BY-SA; never "non-commercial" or
"no derivatives"), always with the author and licence shown next to the photo, as those licences require.
The report says plainly that these are reference images, not photos from the trip.

Lookups: the species' Wikipedia page summary gives its lead image (by scientific name, which redirects
to the article), then Commons gives the author and licence of that file. Results are cached in the
database, including "no image", so each species is looked up about once a month at most.
"""
from __future__ import annotations

import html
import logging
import re
import time
from datetime import datetime, timedelta, timezone
from urllib.parse import quote, unquote

import httpx
from sqlalchemy.orm import Session

from ..models import SpeciesImage, aware

log = logging.getLogger("tripreports.species_images")
UA = {"User-Agent": "TripReports/1.0 (wildlife trip reports; https://trip-reports.onrender.com)",
      "Accept": "application/json"}
COMMONS_API = "https://commons.wikimedia.org/w/api.php"
COMMONS_FILE = re.compile(r"/wikipedia/commons/(?:thumb/)?[0-9a-f]/[0-9a-f]{2}/([^/?#]+)")
RETRY_NONE_AFTER = timedelta(days=30)


def free_licence(name: str) -> bool:
    n = (name or "").lower()
    if "nc" in re.split(r"[^a-z]+", n) or "nd" in re.split(r"[^a-z]+", n) or "non-commercial" in n:
        return False
    return bool(re.match(r"\s*(cc0|cc[ -]by|public domain|pd\b|pdm|attribution)", n))


def _plain(text: str) -> str:
    text = re.sub(r"<[^>]+>", " ", text or "")
    return " ".join(html.unescape(text).split())


def lookup(sci: str, timeout: float = 4.0) -> dict | None:
    """{"url", "credit", "license", "page"} for a freely licensed photo of the species, or None.
    Raises httpx.HTTPError when the lookup couldn't be done (so it isn't cached as "no image")."""
    title = quote(sci.strip().replace(" ", "_"))
    thumb = None
    for wiki in ("en", "es"):
        r = httpx.get(f"https://{wiki}.wikipedia.org/api/rest_v1/page/summary/{title}", headers=UA,
                      timeout=timeout, follow_redirects=True)
        if r.status_code == 404:
            continue
        r.raise_for_status()
        d = r.json()
        thumb = (d.get("originalimage") or {}).get("source") or (d.get("thumbnail") or {}).get("source")
        if thumb:
            break
    if not thumb:
        return None
    m = COMMONS_FILE.search(thumb)
    if not m:
        return None  # an image stored only on Wikipedia itself (often not freely licensed): skip it
    filename = unquote(m.group(1))
    r = httpx.get(COMMONS_API, headers=UA, timeout=timeout, params={
        "action": "query", "format": "json", "prop": "imageinfo", "iiprop": "url|extmetadata",
        "iiurlwidth": 640, "titles": f"File:{filename}"})
    r.raise_for_status()
    pages = (r.json().get("query") or {}).get("pages") or {}
    page = next(iter(pages.values()), {})
    info = (page.get("imageinfo") or [{}])[0]
    meta = info.get("extmetadata") or {}
    licence = _plain((meta.get("LicenseShortName") or {}).get("value", ""))
    if not free_licence(licence):
        return None
    url = info.get("thumburl") or info.get("url")
    if not url:
        return None
    author = _plain((meta.get("Artist") or {}).get("value", "")) or _plain((meta.get("Credit") or {}).get("value", ""))
    return {"url": url, "credit": (author or "Wikimedia Commons")[:120], "license": licence[:80],
            "page": info.get("descriptionurl") or f"https://commons.wikimedia.org/wiki/File:{quote(filename)}"}


def get(db: Session, scis: list[str], budget: float = 4.0) -> dict[str, SpeciesImage]:
    """Cached photos for these species; looks up missing ones until the time budget runs out."""
    out: dict[str, SpeciesImage] = {}
    start = time.monotonic()
    now = datetime.now(timezone.utc)
    changed = False
    for sci in dict.fromkeys(s.strip() for s in scis if s and s.strip()):
        row = db.get(SpeciesImage, sci)
        stale = row is None or (not row.ok and (row.fetched_at is None or now - aware(row.fetched_at) > RETRY_NONE_AFTER))
        if stale and time.monotonic() - start < budget:
            try:
                found = lookup(sci, timeout=max(1.0, min(4.0, budget - (time.monotonic() - start))))
            except (httpx.HTTPError, ValueError) as e:
                log.info("No species photo lookup for %s right now: %s", sci, e)
                found = "error"
            if found != "error":
                row = row or SpeciesImage(sci=sci)
                row.ok = bool(found)
                if found:
                    row.url, row.credit, row.license, row.page = found["url"], found["credit"], found["license"], found["page"]
                row.fetched_at = now
                db.merge(row)
                changed = True
        if row is not None and row.ok:
            out[sci] = row
    if changed:
        db.commit()
    return out


def for_trip(db: Session, trip, org, budget: float = 4.0) -> dict[str, SpeciesImage]:
    if not getattr(org, "species_photos", True):
        return {}
    scis = [s.sci for d in trip.days for s in d.sightings if s.sci]
    try:
        return get(db, scis, budget=budget)
    except Exception as e:  # photos are a nice extra: never break a report over them
        log.warning("Species photos unavailable: %s", e)
        db.rollback()
        return {}
