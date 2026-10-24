"""Season insights across an operator's trips: how often target species are found, best months,
most and least recorded species, and honest lines for marketing."""
from __future__ import annotations

import unicodedata
from dataclasses import dataclass, field

from .freedraft import join_list
from .reportdata import MONTHS, build_tally


def norm(s: str) -> str:
    s = unicodedata.normalize("NFD", (s or "").lower())
    s = "".join(c for c in s if unicodedata.category(c) != "Mn")
    return " ".join("".join(c if c.isalnum() or c == " " else " " for c in s).split())


@dataclass
class SpeciesStat:
    name: str
    sci: str
    trips: int = 0
    months: list = field(default_factory=lambda: [0] * 12)
    max: int = 0


@dataclass
class Insights:
    n_trips: int
    days: int
    guests: int
    month_trips: list
    species: list
    targets: list  # (label, SpeciesStat | None)
    avg_species: int
    has_demo: bool

    def pct(self, k: int) -> int:
        return round(100 * k / self.n_trips) if self.n_trips else 0


def compute(trips, targets_text: str) -> Insights:
    trips = [t for t in trips if t.days]
    month_trips = [0] * 12
    stats: dict[str, SpeciesStat] = {}
    days = guests = total_sp = 0
    # A species typed without a scientific name still counts as the same species as a named row.
    name_sci: dict[str, str] = {}
    for t in trips:
        for d in t.days:
            for x in d.sightings:
                if x.sci and x.name:
                    name_sci.setdefault(norm(x.name), x.sci)
    for t in trips:
        d0 = t.start_date or t.days[0].date
        m = d0.month - 1 if d0 else None
        if m is not None:
            month_trips[m] += 1
        days += len(t.days)
        guests += t.guests or 0
        rows = build_tally(t)
        seen: set[str] = set()
        for r in rows:
            k = (r.sci or name_sci.get(norm(r.name)) or r.name).lower()
            if k in seen:
                continue
            seen.add(k)
            st = stats.get(k)
            if st is None:
                st = stats[k] = SpeciesStat(name=r.name, sci=r.sci or name_sci.get(norm(r.name), ""))
            st.trips += 1
            if m is not None:
                st.months[m] += 1
            st.max = max(st.max, r.max)
        total_sp += len(seen)
    species = sorted(stats.values(), key=lambda s: (-s.trips, s.name.lower()))
    targets = []
    for label in [x.strip() for x in (targets_text or "").split(",") if x.strip()]:
        n = norm(label)
        hit = next((s for s in species if norm(s.name) == n or norm(s.sci) == n), None)
        if not hit and len(n) > 4:
            hit = next((s for s in species if n in norm(s.name) or norm(s.name) in n), None)
        targets.append((label, hit))
    return Insights(n_trips=len(trips), days=days, guests=guests, month_trips=month_trips, species=species,
                    targets=targets, avg_species=round(total_sp / len(trips)) if trips else 0,
                    has_demo=any(t.is_demo for t in trips))


def month_bars(data: Insights, st: SpeciesStat, lang: str) -> list[dict]:
    names = MONTHS.get(lang, MONTHS["en"])
    out = []
    for m in range(12):
        n = data.month_trips[m]
        out.append({"label": names[m][:1].upper(), "name": names[m], "trips": n, "hits": st.months[m],
                    "pct": round(100 * st.months[m] / n) if n else None})
    return out


def best_month(data: Insights, st: SpeciesStat, lang: str) -> tuple[str, int] | None:
    best = None
    for m in range(12):
        n = data.month_trips[m]
        if n and st.months[m]:
            r = st.months[m] / n
            if best is None or r > best[1]:
                best = (m, r)
    if not best:
        return None
    return MONTHS.get(lang, MONTHS["en"])[best[0]], round(best[1] * 100)


LINES = {
    "en": {"target": "{sp} recorded on {p}% of our {n} trips.",
           "avg": "On average, our guests record {a} species per trip, and {t} species in total across our tours."},
    "es": {"target": "{sp}: registrado en el {p}% de nuestras {n} salidas.",
           "avg": "De media, nuestros clientes registran {a} especies por viaje, y {t} especies en total en nuestros tours."},
    "de": {"target": "{sp} auf {p}% unserer {n} Touren nachgewiesen.",
           "avg": "Im Schnitt sehen unsere Gäste {a} Arten pro Tour, insgesamt {t} Arten auf unseren Touren."},
    "fr": {"target": "{sp} observé lors de {p}% de nos {n} sorties.",
           "avg": "En moyenne, nos clients observent {a} espèces par voyage, et {t} espèces au total sur nos circuits."},
}

SEASON = {
    "en": ("This season we ran {n} trips and spent {d} days in the field{g}, recording {t} species in total.",
           " with {g} guests", " {sp} was recorded on {p}% of trips.", "Past results are no guarantee, but they show what our area can offer."),
    "es": ("Esta temporada hicimos {n} salidas y pasamos {d} días en el campo{g}, con {t} especies registradas en total.",
           " con {g} participantes", " {sp} se registró en el {p}% de las salidas.", "Los resultados pasados no garantizan nada, pero muestran lo que nuestra zona puede ofrecer."),
    "de": ("In dieser Saison waren wir auf {n} Touren und {d} Tage draußen{g} und haben insgesamt {t} Arten nachgewiesen.",
           " mit {g} Gästen", " {sp} wurde auf {p}% der Touren nachgewiesen.", "Frühere Ergebnisse sind keine Garantie, zeigen aber, was unsere Region bietet."),
    "fr": ("Cette saison, nous avons mené {n} sorties et passé {d} jours sur le terrain{g}, avec {t} espèces observées au total.",
           " avec {g} participants", " {sp} a été observé lors de {p}% des sorties.", "Les résultats passés ne garantissent rien, mais montrent ce que notre région peut offrir."),
}


def website_lines(data: Insights, lang: str) -> list[str]:
    t = LINES.get(lang, LINES["en"])
    out = [t["target"].format(sp=st.name, p=data.pct(st.trips), n=data.n_trips) for _, st in data.targets if st]
    if data.n_trips:
        out.append(t["avg"].format(a=data.avg_species, t=len(data.species)))
    return out


def free_season_text(data: Insights, org) -> str:
    lang = org.report_lang if org.report_lang in SEASON else "en"
    a, g, tline, close = SEASON[lang]
    text = a.format(n=data.n_trips, d=data.days, t=len(data.species), g=g.format(g=data.guests) if data.guests else "")
    for _, st in data.targets:
        if st:
            text += tline.format(sp=st.name, p=data.pct(st.trips))
    return text + " " + close


def facts_for_ai(data: Insights, org) -> dict:
    return {
        "operator": org.name or "(not given)", "trips": data.n_trips, "daysInField": data.days,
        "guests": data.guests, "speciesTotal": len(data.species),
        "targets": [{"species": st.name, "tripsRecorded": st.trips, "percent": data.pct(st.trips)}
                    for _, st in data.targets if st],
        "mostRecorded": [{"species": s.name, "percentOfTrips": data.pct(s.trips)} for s in data.species[:10]],
        "rarerRecords": [s.name for s in data.species if s.trips == 1][:8],
    }


__all__ = ["compute", "month_bars", "best_month", "website_lines", "free_season_text", "facts_for_ai", "join_list"]
