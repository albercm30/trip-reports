"""Builds everything the report template needs: the day-by-day species tally, highlights,
numbers and labels in the report's language."""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date

REPORT_LANGS = {"en": "English", "es": "Español", "de": "Deutsch", "fr": "Français"}

L = {
    "en": {"day": "Day", "tally": "The tally", "tally_sub": "Every species recorded on the trip, day by day.",
           "species": "Species", "max": "Max", "heard": "h", "heard_key": "h = heard only",
           "unsure_key": "? = unconfirmed identification", "tick_key": "| = seen, not counted",
           "total": "species recorded", "guided_by": "Guided by", "guests": "guests", "made": "Report made with {app}",
           "days": "days", "highlights": "Highlights", "other": "Other", "trip_report": "Trip report", "pdf": "Save as PDF"},
    "es": {"day": "Día", "tally": "El recuento", "tally_sub": "Todas las especies registradas durante el viaje, día a día.",
           "species": "Especie", "max": "Máx.", "heard": "o", "heard_key": "o = solo oída",
           "unsure_key": "? = identificación sin confirmar", "tick_key": "| = vista, sin contar",
           "total": "especies registradas", "guided_by": "Guiado por", "guests": "participantes",
           "made": "Informe creado con {app}", "days": "días", "highlights": "Lo más destacado", "other": "Otras",
           "trip_report": "Informe del viaje", "pdf": "Guardar como PDF"},
    "de": {"day": "Tag", "tally": "Die Artenliste", "tally_sub": "Alle auf der Reise nachgewiesenen Arten, Tag für Tag.",
           "species": "Art", "max": "Max.", "heard": "g", "heard_key": "g = nur gehört",
           "unsure_key": "? = unbestätigte Bestimmung", "tick_key": "| = gesehen, nicht gezählt",
           "total": "Arten nachgewiesen", "guided_by": "Reiseleitung", "guests": "Gäste",
           "made": "Bericht erstellt mit {app}", "days": "Tage", "highlights": "Höhepunkte", "other": "Sonstige",
           "trip_report": "Reisebericht", "pdf": "Als PDF speichern"},
    "fr": {"day": "Jour", "tally": "Le décompte", "tally_sub": "Toutes les espèces observées pendant le voyage, jour par jour.",
           "species": "Espèce", "max": "Max.", "heard": "e", "heard_key": "e = seulement entendue",
           "unsure_key": "? = identification non confirmée", "tick_key": "| = vue, non comptée",
           "total": "espèces observées", "guided_by": "Guidé par", "guests": "participants",
           "made": "Rapport créé avec {app}", "days": "jours", "highlights": "Temps forts", "other": "Autres",
           "trip_report": "Rapport de voyage", "pdf": "Enregistrer en PDF"},
}

GROUPS = {
    "birds": {"en": "Birds", "es": "Aves", "de": "Vögel", "fr": "Oiseaux"},
    "mammals": {"en": "Mammals", "es": "Mamíferos", "de": "Säugetiere", "fr": "Mammifères"},
    "reptiles": {"en": "Reptiles", "es": "Reptiles", "de": "Reptilien", "fr": "Reptiles"},
    "amphibians": {"en": "Amphibians", "es": "Anfibios", "de": "Amphibien", "fr": "Amphibiens"},
    "insects": {"en": "Insects", "es": "Insectos", "de": "Insekten", "fr": "Insectes"},
    "arachnids": {"en": "Spiders and allies", "es": "Arácnidos", "de": "Spinnentiere", "fr": "Arachnides"},
    "fish": {"en": "Fish", "es": "Peces", "de": "Fische", "fr": "Poissons"},
    "other": {"en": "Other", "es": "Otras", "de": "Sonstige", "fr": "Autres"},
}
GROUP_ORDER = ["mammals", "birds", "reptiles", "amphibians", "fish", "insects", "arachnids", "other"]

MONTHS = {
    "en": ["January", "February", "March", "April", "May", "June", "July", "August", "September", "October", "November", "December"],
    "es": ["enero", "febrero", "marzo", "abril", "mayo", "junio", "julio", "agosto", "septiembre", "octubre", "noviembre", "diciembre"],
    "de": ["Januar", "Februar", "März", "April", "Mai", "Juni", "Juli", "August", "September", "Oktober", "November", "Dezember"],
    "fr": ["janvier", "février", "mars", "avril", "mai", "juin", "juillet", "août", "septembre", "octobre", "novembre", "décembre"],
}
WEEKDAYS = {
    "en": ["Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday"],
    "es": ["lunes", "martes", "miércoles", "jueves", "viernes", "sábado", "domingo"],
    "de": ["Montag", "Dienstag", "Mittwoch", "Donnerstag", "Freitag", "Samstag", "Sonntag"],
    "fr": ["lundi", "mardi", "mercredi", "jeudi", "vendredi", "samedi", "dimanche"],
}


def group_label(key: str, lang: str) -> str:
    return GROUPS.get(key, GROUPS["other"]).get(lang, GROUPS.get(key, GROUPS["other"])["en"])


def group_key(label: str) -> str:
    """Map any stored group label (in any language) back to a group key."""
    lab = (label or "").strip().lower()
    for k, names in GROUPS.items():
        if lab in {n.lower() for n in names.values()} or lab == k:
            return k
    return "other" if not lab else lab


def fmt_date(d: date | None, lang: str, style: str = "long") -> str:
    if not d:
        return ""
    m = MONTHS.get(lang, MONTHS["en"])[d.month - 1]
    wd = WEEKDAYS.get(lang, WEEKDAYS["en"])[d.weekday()]
    if style == "day":  # Monday 18 September
        return f"{wd} {d.day} {m}" if lang == "en" else (f"{wd}, {d.day}. {m}" if lang == "de" else f"{wd} {d.day} de {m}" if lang == "es" else f"{wd} {d.day} {m}")
    if style == "dm":
        return f"{d.day} {m}" if lang != "es" else f"{d.day} de {m}"
    return f"{d.day} {m} {d.year}" if lang != "es" else f"{d.day} de {m} de {d.year}"


def date_range(first: date | None, last: date | None, lang: str) -> str:
    if not first:
        return ""
    if not last or first == last:
        return fmt_date(first, lang)
    return f"{fmt_date(first, lang, 'dm')} – {fmt_date(last, lang)}"


@dataclass
class TallyRow:
    name: str
    sci: str
    group: str
    cells: dict = field(default_factory=dict)  # day index -> {"count": int, "heard": bool}
    max: int = 0
    unsure: bool = False
    star: bool = False


def species_key(name: str, sci: str) -> str:
    return (sci or name or "").strip().lower()


def build_tally(trip) -> list[TallyRow]:
    rows: dict[str, TallyRow] = {}
    for di, d in enumerate(trip.days):
        for s in d.sightings:
            k = species_key(s.name, s.sci)
            if not k:
                continue
            r = rows.get(k)
            if r is None:
                r = rows[k] = TallyRow(name=s.name, sci=s.sci, group=group_key(s.group))
            c = s.count or 0
            prev = r.cells.get(di)
            r.cells[di] = {"count": max(prev["count"] if prev else 0, c),
                           "heard": (prev["heard"] and s.heard) if prev else bool(s.heard)}
            r.max = max(r.max, c)
            r.unsure = r.unsure or not s.sure
            r.star = r.star or s.star
            if r.group == "other" and s.group:
                r.group = group_key(s.group)
    return list(rows.values())


def build_report(trip, org, app_name: str) -> dict:
    lang = org.report_lang if org.report_lang in L else "en"
    t = L[lang]
    rows = build_tally(trip)
    groups: dict[str, list[TallyRow]] = {}
    for r in rows:
        groups.setdefault(r.group, []).append(r)
    ordered = sorted(groups.items(), key=lambda kv: GROUP_ORDER.index(kv[0]) if kv[0] in GROUP_ORDER else 99)
    days = list(trip.days)
    first = days[0].date if days else trip.start_date
    last = days[-1].date if days else trip.start_date
    return {
        "lang": lang,
        "t": {k: v.replace("{app}", app_name) for k, v in t.items()},
        "rows": rows,
        "groups": [(group_label(k, lang), v) for k, v in ordered],
        "show_groups": len(groups) > 1,
        "highlights": [r for r in rows if r.star],
        "range": date_range(first, last, lang),
        "day_label": lambda d: fmt_date(d, lang, "day"),
        "has_tick": any(not c["count"] and not c["heard"] for r in rows for c in r.cells.values()),
        "has_heard": any(c["heard"] and not c["count"] for r in rows for c in r.cells.values()),
        "has_unsure": any(r.unsure for r in rows),
        "species_count": len(rows),
    }


def paragraphs(text: str) -> list[str]:
    return [p.strip() for p in (text or "").replace("\r", "").split("\n") if p.strip()]


def report_checks(trip) -> list[tuple[str, str, dict]]:
    """(level, message key, params). level 'warn' blocks the "ready" state, 'info' does not."""
    out = []
    if not trip.days:
        out.append(("warn", "No days added yet.", {}))
    for i, d in enumerate(trip.days, 1):
        if not d.narrative.strip():
            out.append(("warn", "Day {n} has no written report.", {"n": i}))
        elif not d.approved:
            out.append(("warn", "Day {n} hasn't been approved yet.", {"n": i}))
        u = sum(1 for s in d.sightings if not s.sure)
        if u:
            out.append(("info", "Day {n}: unconfirmed identifications ({u}) will show with a “?”.", {"n": i, "u": u}))
    if not trip.intro.strip():
        out.append(("info", "No opening paragraph. The report will start with Day 1.", {}))
    return out
