"""Free drafting with no AI service: turns the guide's notes and sightings into a tidy first draft.

It never adds facts. It cleans up the guide's own notes into sentences and adds short
sentences built only from the species list (highlights, heard-only, unconfirmed, total).
The guide is expected to edit it; with an Anthropic key the app uses Claude instead.
"""
from __future__ import annotations

import re

SHORTHAND = [
    (r"~\s*(\d+(?:[.,]\d+)?)\s*(m|km|metres|meters)\b", r"about \1 \2"),
    (r"~\s*(\d{1,2})(?::(\d{2}))?\b", lambda m: f"around {int(m.group(1)):02d}:{m.group(2) or '00'}"),
    (r"\b(\d+)\s*hrs?\b", r"\1 hours"),
    (r"\b(\d+)\s*mins?\b", r"\1 minutes"),
    (r"\b(\d+)\s*m\b(?!\w)", r"\1 m"),
    (r"\s*\+\s*", " and "),
    (r"!{2,}", "!"),
    (r"\?{2,}", "?"),
    (r"\s*&\s*", " and "),
    (r"\bw/\s*", "with "),
    (r"\bapprox\.?\b", "about"),
]
SHORTHAND_ES = [
    (r"~\s*(\d+(?:[.,]\d+)?)\s*(m|km|metros)\b", r"unos \1 \2"),
    (r"~\s*(\d{1,2})(?::(\d{2}))?\b", lambda m: f"hacia las {int(m.group(1)):02d}:{m.group(2) or '00'}"),
    (r"\b(\d+)\s*h\b", r"\1 horas"),
    (r"\b(\d+)\s*min\b", r"\1 minutos"),
    (r"\s*\+\s*", " y "),
    (r"!{2,}", "!"),
    (r"\s*&\s*", " y "),
]

T = {
    "en": {
        "open_place": "Day {n} took us to {place}.",
        "hl_one": "The highlight was {a}.", "hl_many": "Highlights included {a}.",
        "heard": "We also heard {a}.",
        "unsure_one": "We also had a possible {a}, though we couldn't confirm the identification.",
        "unsure_many": "We also had possible sightings of {a}, though we couldn't confirm the identifications.",
        "total_one": "In all, we recorded 1 species today.", "total": "In all, we recorded {n} species today.",
        "and": "and",
        "intro": "{title}: {days} in {location}. Here is the trip day by day, with the full list of everything we recorded at the end.",
        "intro_noloc": "{title}: {days}. Here is the trip day by day, with the full list of everything we recorded at the end.",
        "day_s": "1 day", "days": "{n} days",
        "summary_hl": "Looking back, the highlights were {a}.",
        "summary_total": "In total we recorded {n} species.",
        "summary_thanks": "Thank you all for your company in the field.",
    },
    "es": {
        "open_place": "El día {n} nos llevó a {place}.",
        "hl_one": "Lo más destacado fue {a}.", "hl_many": "Entre lo más destacado estuvieron {a}.",
        "heard": "También escuchamos {a}.",
        "unsure_one": "También tuvimos un posible {a}, aunque no pudimos confirmar la identificación.",
        "unsure_many": "También tuvimos posibles observaciones de {a}, aunque no pudimos confirmar las identificaciones.",
        "total_one": "En total, registramos 1 especie hoy.", "total": "En total, registramos {n} especies hoy.",
        "and": "y",
        "intro": "{title}: {days} en {location}. Aquí tienes el viaje día a día, con la lista completa de todo lo que registramos al final.",
        "intro_noloc": "{title}: {days}. Aquí tienes el viaje día a día, con la lista completa de todo lo que registramos al final.",
        "day_s": "1 día", "days": "{n} días",
        "summary_hl": "Mirando atrás, lo más destacado fue {a}.",
        "summary_total": "En total registramos {n} especies.",
        "summary_thanks": "Gracias a todos por vuestra compañía en el campo.",
    },
    "de": {
        "open_place": "Tag {n} führte uns nach {place}.",
        "hl_one": "Der Höhepunkt war {a}.", "hl_many": "Zu den Höhepunkten gehörten {a}.",
        "heard": "Außerdem hörten wir {a}.",
        "unsure_one": "Dazu kam ein mögliche(r) {a}, die Bestimmung konnten wir aber nicht bestätigen.",
        "unsure_many": "Dazu kamen mögliche Beobachtungen von {a}, die wir nicht sicher bestätigen konnten.",
        "total_one": "Insgesamt notierten wir heute 1 Art.", "total": "Insgesamt notierten wir heute {n} Arten.",
        "and": "und",
        "intro": "{title}: {days} in {location}. Hier ist die Reise Tag für Tag, mit der vollständigen Artenliste am Ende.",
        "intro_noloc": "{title}: {days}. Hier ist die Reise Tag für Tag, mit der vollständigen Artenliste am Ende.",
        "day_s": "1 Tag", "days": "{n} Tage",
        "summary_hl": "Rückblickend waren die Höhepunkte {a}.",
        "summary_total": "Insgesamt haben wir {n} Arten nachgewiesen.",
        "summary_thanks": "Vielen Dank an alle für die schöne Zeit draußen.",
    },
    "fr": {
        "open_place": "Le jour {n} nous a menés à {place}.",
        "hl_one": "Le temps fort a été {a}.", "hl_many": "Parmi les temps forts : {a}.",
        "heard": "Nous avons aussi entendu {a}.",
        "unsure_one": "Nous avons aussi eu un possible {a}, sans pouvoir confirmer l'identification.",
        "unsure_many": "Nous avons aussi eu des observations possibles de {a}, sans pouvoir confirmer les identifications.",
        "total_one": "Au total, nous avons noté 1 espèce aujourd'hui.", "total": "Au total, nous avons noté {n} espèces aujourd'hui.",
        "and": "et",
        "intro": "{title} : {days} à {location}. Voici le voyage jour par jour, avec la liste complète de nos observations à la fin.",
        "intro_noloc": "{title} : {days}. Voici le voyage jour par jour, avec la liste complète de nos observations à la fin.",
        "day_s": "1 jour", "days": "{n} jours",
        "summary_hl": "Avec le recul, les temps forts ont été {a}.",
        "summary_total": "Au total, nous avons observé {n} espèces.",
        "summary_thanks": "Merci à tous pour votre compagnie sur le terrain.",
    },
}


def _t(lang: str) -> dict:
    return T.get(lang, T["en"])


def join_list(items: list[str], lang: str) -> str:
    items = [i for i in items if i]
    if len(items) <= 1:
        return "".join(items)
    return ", ".join(items[:-1]) + f" {_t(lang)['and']} " + items[-1]


PROPER = {"Indian", "Asian", "African", "American", "European", "Canarian", "Cretan", "Cyprus", "Balearic",
          "Atlantic", "Pallas", "Pallas's", "Andean", "Alpine", "Siberian", "Arctic", "Caspian", "Moroccan"}


def _lower_name(name: str, lang: str) -> str:
    # "Iberian Lynx" reads better as "Iberian lynx" mid-sentence; keep proper adjectives in English.
    if lang == "de":
        return name
    words = name.split()
    out = []
    low = lambda w: w[:1].lower() + w[1:] if len(w) > 1 and not w[1:2].isupper() else w  # noqa: E731
    for i, w in enumerate(words):
        if lang == "en" and i < len(words) - 1 and w[:1].isupper() and (
                w.endswith(("'s", "’s", "an", "ish", "ese")) or w in PROPER):
            out.append(w)  # Spanish, Iberian, Eurasian, Bonelli's... stay capitalised
        else:
            out.append("-".join(low(p) for p in w.split("-")))
    return " ".join(out)


def tidy_notes(notes: str, lang: str) -> str:
    """Turn terse field notes into readable sentences without adding anything."""
    text = (notes or "").replace("\r", "")
    rules = SHORTHAND_ES if lang == "es" else SHORTHAND
    paras = []
    for block in re.split(r"\n\s*\n", text):
        block = ". ".join(" ".join(line.split()).rstrip(" .") if not line.strip()[-1:] in "!?" else " ".join(line.split())
                          for line in block.split("\n") if line.strip())
        block = re.sub(r"([!?])\. ", r"\1 ", block)
        if not block:
            continue
        for pat, rep in rules:
            block = re.sub(pat, rep, block, flags=re.I)
        sentences = re.split(r"(?<=[.!?])\s+|\s*\n\s*", block)
        fixed = []
        for s in sentences:
            s = s.strip(" ,;-")
            if not s:
                continue
            s = s[0].upper() + s[1:]
            if s[-1] not in ".!?":
                s += "."
            fixed.append(s)
        paras.append(" ".join(fixed))
    return "\n\n".join(paras)


def day_draft(n: int, place: str, notes: str, sightings: list, lang: str) -> str:
    t = _t(lang)
    parts: list[str] = []
    body = tidy_notes(notes, lang)
    if place and place.lower() not in body.lower():
        parts.append(t["open_place"].format(n=n, place=place))
    if body:
        parts.append(body)
    extra = []
    stars = [_lower_name(s.name, lang) for s in sightings if s.star and s.sure and s.name]
    if stars:
        extra.append((t["hl_one"] if len(stars) == 1 else t["hl_many"]).format(a=join_list(stars, lang)))
    heard = [_lower_name(s.name, lang) for s in sightings if s.heard and not s.count and s.sure and s.name]
    if heard:
        extra.append(t["heard"].format(a=join_list(heard, lang)))
    unsure = [_lower_name(s.name, lang) for s in sightings if not s.sure and s.name]
    if unsure:
        extra.append((t["unsure_one"] if len(unsure) == 1 else t["unsure_many"]).format(a=join_list(unsure, lang)))
    n_sp = len({(s.sci or s.name).lower() for s in sightings if s.name})
    if n_sp:
        extra.append(t["total_one"] if n_sp == 1 else t["total"].format(n=n_sp))
    if extra:
        parts.append(" ".join(extra))
    text = "\n\n".join(parts)
    return text[0].upper() + text[1:] if text else ""


def intro_summary(title: str, location: str, n_days: int, highlights: list[str], n_species: int, lang: str) -> tuple[str, str]:
    t = _t(lang)
    days = t["day_s"] if n_days == 1 else t["days"].format(n=n_days)
    title = title or ""
    intro = (t["intro"] if location else t["intro_noloc"]).format(title=title, days=days, location=location).lstrip(": ").strip()
    if not title:
        intro = intro[0].upper() + intro[1:]
    s = []
    if highlights:
        s.append(t["summary_hl"].format(a=join_list([_lower_name(h, lang) for h in highlights], lang)))
    if n_species:
        s.append(t["summary_total"].format(n=n_species))
    s.append(t["summary_thanks"])
    return intro, " ".join(s)
