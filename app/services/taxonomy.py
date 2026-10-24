"""Checks species names against the GBIF Backbone Taxonomy (CC BY 4.0, commercial use allowed
with attribution). Used so a scientific name the model wrote is confirmed to exist before a
guide sees it as "checked". Network problems never block the guide; the row just stays unchecked.
"""
from __future__ import annotations

import logging
from functools import lru_cache

import httpx

from ..config import settings

log = logging.getLogger("tripreports.taxonomy")
GBIF = "https://api.gbif.org/v1"
BACKBONE = "d7dddbf4-2cf0-4f39-9b2a-bb099caae36c"
RANKS = {"SPECIES", "SUBSPECIES", "VARIETY", "FORM"}
GROUP_BY_CLASS = {
    "Aves": "birds", "Mammalia": "mammals", "Reptilia": "reptiles", "Squamata": "reptiles",
    "Testudines": "reptiles", "Crocodylia": "reptiles", "Amphibia": "amphibians",
    "Insecta": "insects", "Arachnida": "arachnids", "Actinopterygii": "fish", "Elasmobranchii": "fish",
}


@lru_cache(maxsize=4096)
def match_scientific(sci: str) -> dict | None:
    """Return {'key', 'canonical', 'class'} if GBIF knows this species name, else None."""
    if not settings.gbif_check or not sci.strip():
        return None
    try:
        r = httpx.get(f"{GBIF}/species/match", params={"name": sci.strip(), "strict": "true"}, timeout=4.0)
        r.raise_for_status()
        d = r.json()
    except Exception as e:  # network, timeout, bad JSON
        log.info("GBIF match failed for %r: %s", sci, e)
        raise LookupError("unavailable") from e
    if d.get("matchType") in ("EXACT", "FUZZY") and d.get("rank") in RANKS and d.get("confidence", 0) >= 90:
        return {"key": d.get("acceptedUsageKey") or d.get("usageKey"),
                "canonical": d.get("canonicalName") or sci, "class": d.get("class", "")}
    return None


def _plain(s: str) -> str:
    import unicodedata
    s = unicodedata.normalize("NFD", s.lower())
    s = "".join(c for c in s if unicodedata.category(c) != "Mn")
    return " ".join(s.replace("-", " ").replace("’", "'").split())


@lru_cache(maxsize=4096)
def match_common(name: str) -> dict | None:
    """Find a species by its common name (English, Spanish, German, French...).
    Only an exact common-name match is accepted, so a vague name never gets a guessed species."""
    if not settings.gbif_check or len(name.strip()) < 3:
        return None
    try:
        r = httpx.get(f"{GBIF}/species/search", timeout=4.0, params={
            "q": name.strip(), "qField": "VERNACULAR", "datasetKey": BACKBONE,
            "rank": "SPECIES", "status": "ACCEPTED", "limit": 10})
        r.raise_for_status()
        results = r.json().get("results", [])
    except Exception as e:
        log.info("GBIF common-name search failed for %r: %s", name, e)
        raise LookupError("unavailable") from e
    want = _plain(name)
    for res in results:
        names = {_plain(v.get("vernacularName", "")) for v in res.get("vernacularNames", [])}
        if want in names and res.get("canonicalName"):
            return {"key": res.get("nubKey") or res.get("key"), "canonical": res["canonicalName"],
                    "class": res.get("class", "")}
    return None


def group_for(cls: str, lang: str) -> str:
    from .reportdata import group_label
    return group_label(GROUP_BY_CLASS.get(cls, "other"), lang)


def check_rows(rows: list[dict]) -> list[dict]:
    """Annotate rows with taxon_key/taxon_status. A scientific name GBIF does not know is kept,
    but the row is marked unsure so the guide checks it before anything is sent."""
    for row in rows:
        row.setdefault("taxon_key", None)
        row.setdefault("taxon_status", "unchecked")
        sci = row.get("sci", "")
        if not settings.gbif_check:
            continue
        if not sci:
            # No scientific name yet (free parser): look the common name up, exact matches only.
            if not row.get("name") or row.get("sure") is False:
                continue
            try:
                m = match_common(row["name"])
            except LookupError:
                continue
            if m:
                row.update(taxon_key=m["key"], taxon_status="matched", sci=m["canonical"], _class=m["class"])
            continue
        try:
            m = match_scientific(sci)
        except LookupError:
            continue
        if m:
            row["taxon_key"] = m["key"]
            row["taxon_status"] = "matched"
            row["sci"] = m["canonical"]
            row["_class"] = m["class"]
        else:
            row["taxon_status"] = "unmatched"
            row["sure"] = False
    return rows
