"""Turns a guide's rough tally ("40 griffons, lynx x1, heard eagle owl, warbler?") into rows.

The Claude API does this best. This rule-based parser is the fallback when AI is not
configured or not available, and it is also used to sanity-check counts.
"""
from __future__ import annotations

import re
import unicodedata

WORD_NUM = {
    "one": 1, "a": 1, "an": 1, "two": 2, "three": 3, "four": 4, "five": 5, "six": 6, "seven": 7,
    "eight": 8, "nine": 9, "ten": 10, "eleven": 11, "twelve": 12, "fifteen": 15, "twenty": 20,
    "thirty": 30, "forty": 40, "fifty": 50, "hundred": 100, "dozen": 12,
    "un": 1, "uno": 1, "una": 1, "dos": 2, "tres": 3, "cuatro": 4, "cinco": 5, "seis": 6,
    "siete": 7, "ocho": 8, "nueve": 9, "diez": 10, "once": 11, "doce": 12, "quince": 15,
    "veinte": 20, "treinta": 30, "cuarenta": 40, "cincuenta": 50, "cien": 100, "docena": 12,
    "pair": 2, "pareja": 2, "couple": 2,
}
VAGUE = re.compile(r"\b(some|several|few|a few|lots of|many|unidentified|unknown|sp\.?|spp\.?|kind of|sort of|"
                   r"algunos|algunas|varios|varias|muchos|muchas|sin identificar|tipo de|especie de)\b", re.I)
DOUBT = re.compile(r"(\?|\b(probably|probable|prob\.?|possible|poss\.?|maybe|perhaps|likely|"
                   r"posible|probablemente|quiz[aá]s?|tal vez)\b)", re.I)
HEARD = re.compile(r"\b(heard( only)?|calling|call(ed)?|o[ií]d[oa]s?|escuchad[oa]s?|cantando|(^|\s)h(\s|$))\b|\(h\)", re.I)
STAR = re.compile(r"!+")
SPLIT = re.compile(r"[\n;,•·]+|\s+\band\b\s+|\s+\by\b\s+", re.I)
FILLER = re.compile(r"\b(we saw|saw|seen|spotted|also|plus|vimos|visto|vistos|vista|vistas|tambi[eé]n|"
                    r"the|el|la|los|las|of|de|del)\b", re.I)
GENERIC = {"bird", "birds", "raptor", "raptors", "eagle", "eagles", "warbler", "warblers", "duck", "ducks",
           "gull", "gulls", "hawk", "hawks", "owl", "owls", "deer", "snake", "lizard", "frog", "bat", "bats",
           "ave", "aves", "rapaz", "rapaces", "aguila", "águila", "aguilas", "águilas", "pato", "patos",
           "gaviota", "gaviotas", "buho", "búho", "murcielago", "murciélago", "serpiente", "lagartija", "rana",
           "curruca", "currucas", "mariposa", "butterfly", "dragonfly"}


def _norm(s: str) -> str:
    s = unicodedata.normalize("NFKC", s)
    return re.sub(r"\s+", " ", s).strip()


def _sing(w: str) -> str:
    if len(w) <= 4 or "'" in w or "’" in w:
        return w
    if w.endswith("ies"):
        return w[:-3] + "y"
    if w.endswith(("ches", "shes", "sses", "xes")):
        return w[:-2]
    if w.endswith("s") and not w.endswith(("ss", "us", "is")):
        return w[:-1]
    return w


def _singular_title(name: str) -> str:
    out = " ".join(_sing(w) for w in name.split())
    return out[:1].upper() + out[1:]


def parse_entry(text: str) -> dict | None:
    raw = _norm(text)
    if not raw:
        return None
    s = raw
    star = bool(STAR.search(s))
    s = STAR.sub(" ", s).strip()
    if re.search(r"\b(pair|pareja)\b", s, re.I) and not re.search(r"\d", s):
        s = re.sub(r"\b(a|an|one|una|un)\s+(pair|pareja)\b", r"\2", s, flags=re.I)
        s = re.sub(r"\s*\b(pair|pareja)\b\s*$", "", s, flags=re.I)
        if s != raw.replace("!", "").strip():
            s = "2 " + re.sub(r"^\s*(pair|pareja)\s+(of|de)?\s*", "", s, flags=re.I)
    sure = not bool(DOUBT.search(s))
    heard = bool(HEARD.search(s))
    vague = bool(VAGUE.search(s))
    count: int | None = None

    m = re.search(r"(?:[x×]\s*(\d{1,5})\b|\((\d{1,5})\)|\b(\d{1,5})\s*[x×]\b)", s, re.I)
    if m:
        count = int(next(g for g in m.groups() if g))
        s = s[:m.start()] + " " + s[m.end():]
    else:
        m = re.match(r"\s*(\d{1,5})\+?\s+", s)
        if m:
            count = int(m.group(1))
            s = s[m.end():]
        else:
            m = re.match(r"\s*(an?|one|two|three|four|five|six|seven|eight|nine|ten|eleven|twelve|fifteen|twenty|"
                         r"thirty|forty|fifty|hundred|dozen|pair|couple|un|uno|una|dos|tres|cuatro|cinco|seis|siete|"
                         r"ocho|nueve|diez|once|doce|quince|veinte|treinta|cuarenta|cincuenta|cien|docena|pareja)\b"
                         r"(\s+(of|de))?\s+", s, re.I)
            if m:
                count = WORD_NUM.get(m.group(1).lower())
                s = s[m.end():]
            else:
                m = re.search(r"\b(\d{1,5})\s*$", s)
                if m:
                    count = int(m.group(1))
                    s = s[:m.start()]
    s = STAR.sub(" ", s)
    s = DOUBT.sub(" ", s)
    s = HEARD.sub(" ", s)
    s = VAGUE.sub(" ", s)
    s = FILLER.sub(" ", s)
    s = re.sub(r"[^\w\s'’-]", " ", s)
    s = re.sub(r"\s+", " ", s).strip(" -'")
    if not s or s.isdigit():
        return None
    name = _singular_title(s.lower()) if s == s.lower() or s == s.upper() else s
    if vague or name.lower() in GENERIC or name.lower().rstrip("s") in GENERIC:
        sure = False
    return {"name": name[:120], "sci": "", "count": count, "heard": heard and not count,
            "sure": sure, "star": star, "group": ""}


def parse_tally(text: str) -> list[dict]:
    """Split free text into species rows. Duplicate names are merged keeping the highest count."""
    out: dict[str, dict] = {}
    for part in SPLIT.split(text or ""):
        row = parse_entry(part)
        if not row:
            continue
        key = row["name"].lower()
        if key in out:
            prev = out[key]
            if row["count"] and (not prev["count"] or row["count"] > prev["count"]):
                prev["count"] = row["count"]
            prev["star"] = prev["star"] or row["star"]
            prev["sure"] = prev["sure"] and row["sure"]
        else:
            out[key] = row
    return list(out.values())


def clean_ai_rows(rows) -> list[dict]:
    """Validate the JSON that comes back from the model. Never trust its shape."""
    out = []
    if not isinstance(rows, list):
        return out
    for o in rows[:300]:
        if not isinstance(o, dict) or not str(o.get("name", "")).strip():
            continue
        c = o.get("count")
        try:
            c = None if c in (None, "") else max(0, int(round(float(c))))
        except (TypeError, ValueError):
            c = None
        out.append({
            "name": str(o.get("name", "")).strip()[:120],
            "sci": str(o.get("sci", "") or "").strip()[:120],
            "count": c,
            "heard": bool(o.get("heard")),
            "sure": o.get("sure") is not False,
            "star": bool(o.get("star")),
            "group": str(o.get("group", "") or "").strip()[:40],
        })
    return out
