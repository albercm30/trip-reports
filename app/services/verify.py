"""Deterministic checks on what the AI produced. The AI is good at reading messy notes and writing,
but numbers, negations and names must match the guide's own words exactly, so the app checks them
with plain code instead of trusting the model:

- species rows: the count must come from the guide's words, "no lynx" is never a sighting,
  "?" and "posible" keep a row unconfirmed, and species the free parser reads with certainty
  but the AI missed are added back;
- written text (day reports, opening, closing): no species that isn't on the list, no numbers that
  aren't in the notes, unconfirmed species described as possible, one language throughout.
"""
from __future__ import annotations

import re

from .species import (DOUBT, GENERIC, VAGUE, Vocab, _prepare, default_vocab, norm, parse_entry, parse_tally,
                      sing_all, strip_accents)

# ------------------------------------------------------------------ species rows
NEG_BEFORE = re.compile(
    r"(\bno\s+(?:vimos|hemos visto|hubo|vi|se vio|se vieron|aparecio|aparecieron|encontramos|tuvimos)?\s*(?:ni\s+)?"
    r"(?:el|la|los|las|un|una|ningun|ninguna|rastro de|ni rastro de)?\s*$"
    r"|\bsin\s+(?:rastro de\s+)?(?:el|la|los|las)?\s*$"
    r"|\bni\s+(?:rastro de\s+)?(?:el|la|los|las)?\s*$"
    r"|\b(?:no|not|never|without|missed|dipped on|didn't see|did not see|didnt see|no sign of|not a single)"
    r"\s+(?:any|the|a|an)?\s*$)", re.I)
CORRECTION_BEFORE = re.compile(r"\d\s*,?\s*(?:no|not)\s*,?\s*$", re.I)


def _find(src_n: str, text_n: str) -> int:
    i = text_n.find(src_n)
    if i >= 0:
        return i
    words = src_n.split()
    for w in sorted(words, key=len, reverse=True):  # the most distinctive word of a slightly misquoted source
        if len(w) >= 4:
            m = re.search(r"\b" + re.escape(w), text_n)
            if m:
                return m.start()
    return -1


def _clause_before(text_n: str, idx: int) -> str:
    before = text_n[:idx]
    cut = max(before.rfind(c) for c in ".;\n!?")
    return before[cut + 1:][-60:]


def _sentence_at(text: str, needle_n: str) -> str:
    for s in re.split(r"(?<=[.!?\n])\s*", text):
        if needle_n and needle_n in norm(s):
            return s
    return ""


def _numbers(s: str) -> set[int]:
    return {int(n) for n in re.findall(r"\b\d{1,5}\b", _prepare(s))}


def check_species_rows(rows: list[dict], text: str, vocab: Vocab | None = None, lang: str = "en",
                       tally: str = "") -> tuple[list[dict], list[str]]:
    """Fix or drop AI species rows using the guide's own words. Returns (rows, notes about changes)."""
    vocab = vocab or default_vocab()
    text_n = norm(text)
    marks = norm(text.replace("?", " qmark ").replace("!", " xmark "))
    out, changes = [], []
    for r in rows:
        src = r.get("source") or r.get("name", "")
        src_n = norm(src)
        idx = _find(src_n, text_n)
        # 1. negations: "no vimos la nutria", "no lynx today"
        if idx >= 0:
            before = _clause_before(text_n, idx)
            if NEG_BEFORE.search(before) and not CORRECTION_BEFORE.search(before):
                changes.append(f"dropped {r['name']}: the guide says it was not seen")
                continue
        if re.match(r"^\s*(no|not|sin|ni)\b", src_n) and not re.match(r"^\s*no\s+\d", src_n):
            changes.append(f"dropped {r['name']}: the guide says it was not seen")
            continue
        # 2. the count must be in the guide's words for this species
        free = parse_entry(_prepare(src), vocab)
        nums = _numbers(src)
        if free and free.get("count") is not None and len(nums) <= 1 and r.get("count") != free["count"]:
            if r.get("count") is not None:
                changes.append(f"{r['name']}: count {r['count']} -> {free['count']} (from the guide's words)")
            r["count"] = free["count"]
        elif r.get("count") is not None and r["count"] > 1 and not nums and not (free and free.get("count")):
            sentence_nums = _numbers(_sentence_at(text, src_n.split()[0] if src_n else ""))
            if r["count"] not in sentence_nums:
                changes.append(f"{r['name']}: removed count {r['count']}, the guide didn't give one")
                r["count"] = None
        # 3. doubt and highlights right where the guide wrote the name: "posible zifio?", "tortuga boba!"
        mi = _find(src_n, marks) if src_n else -1
        after = marks[mi + len(src_n): mi + len(src_n) + 12].split()[:1] if mi >= 0 else []
        if DOUBT.search(src) or "qmark" in after:
            r["sure"] = False
        if "!" in src or "xmark" in after:
            r["star"] = True
        # 4. if the guide literally wrote a species' name, that name wins over the model's guess
        if free and free.get("sci") and free.get("_entry") and r.get("sci") and norm(free["sci"]) != norm(r["sci"]) \
                and (free.get("sure") or DOUBT.search(src)) and _exact_name(free["_entry"], src, vocab):
            e = free.get("_entry") or {}
            if e:
                changes.append(f"{r['name']}: corrected to {e['en']} as written by the guide")
                r.update(name=e["es"] if lang == "es" else e["en"], sci=e["sci"], group=e["group"] or r.get("group", ""))
        # 5. the model gave a name but no scientific name: look the name up
        if not r.get("sci") and r.get("name") and not VAGUE.search(src) and norm(r["name"]) not in GENERIC \
                and sing_all(norm(r["name"])) not in GENERIC:
            e, sc = vocab.match(r["name"])
            if not (e and sc >= 0.92) and free and free.get("_entry") and free.get("sure"):
                e, sc = free["_entry"], 1.0
            if e and sc >= 0.92:
                changes.append(f"{r['name']}: identified as {e['en']}")
                r.update(name=e["es"] if lang == "es" else e["en"], sci=e["sci"], group=r.get("group") or e["group"])
                if not DOUBT.search(src) and "qmark" not in after:
                    r["sure"] = True
        out.append(r)
    out = _merge(out)
    # 6. recall: species the free parser reads with certainty from the tally but the AI left out
    if tally.strip():
        have = {norm(x.get("sci") or "") for x in out if x.get("sci")} | {norm(x["name"]) for x in out}
        for f in parse_tally(tally, vocab, lang):
            if not f.get("sure") or not f.get("sci"):
                continue
            if norm(f["sci"]) in have or norm(f["name"]) in have:
                continue
            idx = _find(norm(f["source"]), text_n)
            if idx >= 0 and NEG_BEFORE.search(_clause_before(text_n, idx)):
                continue
            f.pop("_entry", None)
            changes.append(f"added {f['name']}, which the AI missed")
            out.append(f)
            have.add(norm(f["sci"]))
    return out, changes


def _exact_name(entry: dict, src: str, vocab: Vocab) -> bool:
    """True when the guide's words name this species outright (not just a fuzzy guess)."""
    s = sing_all(norm(_prepare(src)))
    names = [sing_all(norm(entry.get(k) or "")) for k in ("en", "es", "sci")]
    if any(n and n in s for n in names):
        return True
    e, sc = vocab.match(re.sub(r"\d+|\bx\b", " ", s))
    return bool(e and e is entry and sc >= 0.95)


def _merge(rows: list[dict]) -> list[dict]:
    out: dict[str, dict] = {}
    for r in rows:
        k = norm(r.get("sci") or "") or norm(r.get("name", ""))
        if k in out:
            p = out[k]
            if r.get("count") and (not p.get("count") or r["count"] > p["count"]):
                p["count"] = r["count"]
            p["star"] = p.get("star") or r.get("star")
            p["sure"] = p.get("sure") and r.get("sure")
        else:
            out[k] = r
    return list(out.values())


# ------------------------------------------------------------------ written text
LANG_WORDS = {
    "es": {"el", "la", "los", "las", "de", "del", "y", "que", "en", "un", "una", "con", "por", "para", "nos", "muy",
           "pero", "tambien", "fue", "era", "mientras", "cuando", "donde", "hasta", "como", "nuestro", "nuestra"},
    "en": {"the", "and", "we", "of", "to", "in", "with", "for", "was", "were", "very", "but", "also", "then",
           "our", "as", "while", "when", "where", "until", "it", "its", "this", "that", "they"},
    "de": {"der", "die", "das", "und", "wir", "mit", "ein", "eine", "nicht", "auch", "dann", "war", "waren",
           "unser", "unsere", "als", "wie", "auf", "den", "dem", "zu"},
    "fr": {"le", "la", "les", "et", "nous", "avec", "un", "une", "pas", "aussi", "puis", "etait", "notre", "nos",
           "comme", "sur", "dans", "des", "du", "au"},
}
HEDGE = re.compile(r"\b(possibl[ey]|probabl[ey]|perhaps|maybe|might|may have|likely|what (?:looked|seemed)|"
                   r"posible|posiblemente|probable|probablemente|quiz[aá]s?|tal vez|parec[ií]a|parec[ií]an|pudo|"
                   r"podr[ií]a|sin confirmar|unconfirmed|wahrscheinlich|vielleicht|m[oö]glich|peut[- ][eê]tre|"
                   r"probablement|possible)\b", re.I)
NUMWORDS = {
    "en": {"two": 2, "three": 3, "four": 4, "five": 5, "six": 6, "seven": 7, "eight": 8, "nine": 9, "ten": 10,
           "eleven": 11, "twelve": 12, "fifteen": 15, "twenty": 20, "thirty": 30, "forty": 40, "fifty": 50,
           "hundred": 100, "dozen": 12},
    "es": {"dos": 2, "tres": 3, "cuatro": 4, "cinco": 5, "seis": 6, "siete": 7, "ocho": 8, "nueve": 9, "diez": 10,
           "once": 11, "doce": 12, "quince": 15, "veinte": 20, "treinta": 30, "cuarenta": 40, "cincuenta": 50,
           "cien": 100, "docena": 12},
    "de": {"zwei": 2, "drei": 3, "vier": 4, "funf": 5, "sechs": 6, "sieben": 7, "acht": 8, "neun": 9, "zehn": 10,
           "zwanzig": 20, "dreissig": 30, "vierzig": 40, "funfzig": 50, "hundert": 100},
    "fr": {"deux": 2, "trois": 3, "quatre": 4, "cinq": 5, "sept": 7, "huit": 8, "neuf": 9, "dix": 10,
           "vingt": 20, "trente": 30, "quarante": 40, "cinquante": 50, "cent": 100},
}
LANG_NAMES = {"en": "English", "es": "Spanish", "de": "German", "fr": "French"}


def detect_lang(text: str) -> str | None:
    words = re.findall(r"[a-z]+", strip_accents((text or "").lower()))
    scores = {k: sum(w in v for w in words) for k, v in LANG_WORDS.items()}
    best = max(scores, key=scores.get)
    second = max(v for k, v in scores.items() if k != best)
    if scores[best] < 3 or scores[best] < 1.5 * max(second, 1):
        return None
    return best


def _names_index(vocab: Vocab) -> dict[str, dict]:
    idx = {}
    for e in vocab.entries:
        for n in (e.get("en"), e.get("es"), e.get("sci")):
            k = sing_all(norm(n or ""))
            if len(k) >= 4 and " " in k or len(k) >= 6:  # skip short one-word names that are common words
                idx.setdefault(k, e)
    return idx


_INDEX: dict[int, dict] = {}


def mentioned_species(text: str, vocab: Vocab | None = None) -> list[dict]:
    """Species from the vocabulary named in a piece of text (exact names, any language)."""
    vocab = vocab or default_vocab()
    index = _INDEX.get(id(vocab))
    if index is None:
        index = _INDEX[id(vocab)] = _names_index(vocab)
    words = sing_all(norm(text)).split()
    found, seen = [], set()
    for n in (4, 3, 2, 1):
        for i in range(len(words) - n + 1):
            k = " ".join(words[i:i + n])
            e = index.get(k)
            if e and e["sci"] not in seen:
                seen.add(e["sci"])
                found.append(e)
    return found


NEG_WORDS = re.compile(r"\b(no|not|never|without|didn'?t|none|sin|ni|nunca|ningun[oa]?|kein[e]?|nicht|pas|aucun[e]?)\b",
                       re.I)


def _only_negated(text: str, e: dict) -> bool:
    keys = [k for k in (sing_all(norm(e.get("en", ""))), sing_all(norm(e.get("es", ""))), sing_all(norm(e.get("sci", "")))) if k]
    hits = [sent for sent in re.split(r"(?<=[.!?;])\s+", text)
            if any(re.search(r"\b" + re.escape(k) + r"\b", sing_all(norm(sent))) for k in keys)]
    return bool(hits) and all(NEG_WORDS.search(h) for h in hits)


def check_text(text: str, *, lang: str, species: list, notes: str = "", allowed_numbers: set[int] | None = None,
               vocab: Vocab | None = None) -> list[dict]:
    """Problems in a written report. Each is {'kind', 'what'}; kinds: language, species, number, certainty."""
    text = (text or "").strip()
    if not text:
        return []
    vocab = vocab or default_vocab()
    problems: list[dict] = []
    # plain prose: no markdown, lists or scientific names
    if re.search(r"\*\*|^#+\s|^\s*[-•*]\s+\S", text, re.M):
        problems.append({"kind": "format", "what": "markdown"})
    for s_ in species:
        if getattr(s_, "sci", "") and len(s_.sci) > 5 and s_.sci.lower() in text.lower():
            problems.append({"kind": "format", "what": s_.sci})
            break
    # one language throughout
    for para in [p for p in re.split(r"\n\s*\n", text) if len(p.split()) >= 8]:
        found = detect_lang(para)
        if found and found != lang:
            problems.append({"kind": "language", "what": LANG_NAMES.get(found, found)})
            break
    # only species from the list (or that the notes talk about, e.g. "we hoped for orcas")
    listed_sci = {norm(s.sci) for s in species if getattr(s, "sci", "")}
    listed_names = {sing_all(norm(s.name)) for s in species if s.name}
    in_notes = {e["sci"] for e in mentioned_species(notes, vocab)}
    for e in mentioned_species(text, vocab):
        if norm(e["sci"]) in listed_sci:
            continue
        if sing_all(norm(e["en"])) in listed_names or sing_all(norm(e["es"])) in listed_names:
            continue
        if e["sci"] in in_notes and _only_negated(text, e):
            continue  # "we didn't see the sperm whales this time", as the notes say
        problems.append({"kind": "species", "what": e["es"] if lang == "es" else e["en"]})
    # numbers must come from the notes, the counts or the trip details
    allowed = set(allowed_numbers or set()) | _numbers(notes) | {s.count for s in species if getattr(s, "count", None)}
    found_nums = {int(n) for n in re.findall(r"\b\d{1,5}\b", text)}
    words = NUMWORDS.get(lang, {})
    for w in re.findall(r"[^\W\d_]+", text):
        v = words.get(strip_accents(w.lower()))
        if v:
            found_nums.add(v)
    for n in sorted(found_nums):
        if n > 1 and n not in allowed and not (1900 <= n <= 2100):
            problems.append({"kind": "number", "what": str(n)})
    # unconfirmed species must not be stated as certain
    for s in species:
        if getattr(s, "sure", True) or not s.name:
            continue
        keys = {sing_all(norm(s.name))}
        if s.sci:
            for e in vocab.entries:
                if norm(e["sci"]) == norm(s.sci):
                    keys |= {sing_all(norm(e["en"])), sing_all(norm(e["es"]))}
        for sent in re.split(r"(?<=[.!?])\s+", text):
            sn = sing_all(norm(sent))
            if any(k and re.search(r"\b" + re.escape(k) + r"\b", sn) for k in keys) and not HEDGE.search(sent):
                problems.append({"kind": "certainty", "what": s.name})
                break
    return problems


def day_problems(day, trip, n: int) -> list[dict]:
    allowed = {n, len(trip.days)} | ({trip.guests} if trip.guests else set())
    if day.date:
        allowed |= {day.date.day, day.date.year}
    return check_text(day.narrative, lang=trip.report_lang, species=list(day.sightings), notes=day.notes or "",
                      allowed_numbers=allowed)


def trip_text_problems(trip, n_species: int) -> list[dict]:
    species = [s for d in trip.days for s in d.sightings]
    notes = "\n".join((d.notes or "") + "\n" + (d.narrative or "") for d in trip.days)
    allowed = {len(trip.days), n_species} | ({trip.guests} if trip.guests else set())
    out = []
    for field in ("intro", "summary"):
        out += check_text(getattr(trip, field) or "", lang=trip.report_lang, species=species, notes=notes,
                          allowed_numbers=allowed)
    return out


def feedback(problems: list[dict], lang: str) -> str:
    """Instructions for a corrective rewrite."""
    lines = []
    for p in problems:
        if p["kind"] == "language":
            lines.append(f"Parts were written in {p['what']}. Write everything in {LANG_NAMES.get(lang, 'English')}.")
        elif p["kind"] == "species":
            lines.append(f"You mentioned {p['what']}, which is not on the species list. Remove it.")
        elif p["kind"] == "number":
            lines.append(f"You used the number {p['what']}, which is not in the notes. Remove it or use the real number.")
        elif p["kind"] == "format":
            lines.append("Plain prose only: no headings, lists, bold or scientific names, and no checklist at the end.")
        elif p["kind"] == "claim":
            lines.append(f"\"{p['what']}\" is not in the notes ({p.get('why') or 'unsupported'}). Remove it.")
        elif p["kind"] == "certainty":
            lines.append(f"{p['what']} is UNCONFIRMED: describe it as possible or probable, never as certain.")
    return "\n".join(f"- {x}" for x in lines)


def tidy(text: str) -> str:
    """Last safety net for prose: drop markdown emphasis, headings and a trailing checklist."""
    lines = (text or "").replace("\r", "").split("\n")
    out = []
    for ln in lines:
        if re.match(r"^\s*(#+\s|[-•*]\s+\S)", ln):
            continue  # list items and headings: the report already has the checklist
        if re.fullmatch(r"\s*\*\*[^*]+\*\*:?\s*", ln):
            continue  # a bold heading line on its own
        out.append(ln.replace("**", "").replace("__", ""))
    return re.sub(r"\n{3,}", "\n\n", "\n".join(out)).strip()
