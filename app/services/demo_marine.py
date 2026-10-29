"""Whale-watching example for the Canary Islands: one finished outing off La Palma's west coast and a
year of outings with realistic seasonality, so operators like whale-watching companies see their own
world in the app. Every sentence of the example report is backed by the guide's notes (the app's own
fact-checks find nothing to flag in it)."""
from __future__ import annotations

import random
from datetime import date, datetime, timedelta, timezone

from sqlalchemy.orm import Session

from ..models import Day, Organization, Point, Sighting, Trip
from .reportdata import group_label

LOCATION = {"es": "Costa oeste de La Palma, Canarias", "en": "West coast of La Palma, Canary Islands"}

# key: (English, Spanish, scientific, group)
SP = {
    "gma": ("Short-finned Pilot Whale", "Calderón tropical", "Globicephala macrorhynchus", "mammals"),
    "ttr": ("Common Bottlenose Dolphin", "Delfín mular", "Tursiops truncatus", "mammals"),
    "sfr": ("Atlantic Spotted Dolphin", "Delfín moteado del Atlántico", "Stenella frontalis", "mammals"),
    "dde": ("Short-beaked Common Dolphin", "Delfín común", "Delphinus delphis", "mammals"),
    "ggr": ("Risso's Dolphin", "Calderón gris", "Grampus griseus", "mammals"),
    "sbr": ("Rough-toothed Dolphin", "Delfín de dientes rugosos", "Steno bredanensis", "mammals"),
    "pma": ("Sperm Whale", "Cachalote", "Physeter macrocephalus", "mammals"),
    "bed": ("Bryde's Whale", "Rorcual tropical", "Balaenoptera edeni", "mammals"),
    "bph": ("Fin Whale", "Rorcual común", "Balaenoptera physalus", "mammals"),
    "mno": ("Humpback Whale", "Yubarta", "Megaptera novaeangliae", "mammals"),
    "oor": ("Killer Whale", "Orca", "Orcinus orca", "mammals"),
    "zca": ("Cuvier's Beaked Whale", "Zifio de Cuvier", "Ziphius cavirostris", "mammals"),
    "mde": ("Blainville's Beaked Whale", "Zifio de Blainville", "Mesoplodon densirostris", "mammals"),
    "cca": ("Loggerhead Sea Turtle", "Tortuga boba", "Caretta caretta", "reptiles"),
    "cbo": ("Cory's Shearwater", "Pardela cenicienta", "Calonectris borealis", "birds"),
    "shi": ("Common Tern", "Charrán común", "Sterna hirundo", "birds"),
    "mmo": ("Ocean Sunfish", "Pez luna", "Mola mola", "fish"),
    "mmb": ("Spinetail Devil Ray", "Manta diablo", "Mobula mobular", "fish"),
}

EX = {
    "es": {
        "title": "Avistamiento de cetáceos · salida de mañana",
        "place": "Frente a Tazacorte",
        "notes": "Salida de mañana desde el puerto de Tazacorte (costa oeste), 18 personas. Mar en calma, algo de calima. "
                 "A los 20 min grupo grande de calderones tropicales, unos 25 con varias crías, descansando en superficie, "
                 "se acercaron al barco muy tranquilos. Luego delfines mulares x8 que se unieron a los calderones! "
                 "Pardelas cenicientas por todos lados, muchas posadas en el agua. A la vuelta una tortuga boba!! "
                 "comiendo medusas cerca de la superficie. Posible zifio de Cuvier muy lejos, solo un soplo y el dorso, "
                 "no confirmado. Ningún cachalote hoy.",
        "narrative": "Salimos del puerto de Tazacorte con 18 personas a bordo, el mar en calma y algo de calima. A los "
                     "veinte minutos encontramos un gran grupo de unos 25 calderones tropicales, con varias crías, "
                     "descansando en superficie; se acercaron al barco con total tranquilidad. Poco después, ocho delfines "
                     "mulares se unieron a los calderones, un encuentro precioso.\n\n"
                     "Las pardelas cenicientas nos acompañaron durante toda la salida, muchas de ellas posadas en el agua. "
                     "Ya de vuelta llegó el gran momento del día: una tortuga boba comiendo medusas cerca de la superficie. "
                     "A lo lejos vimos también lo que probablemente era un zifio de Cuvier, aunque solo asomaron un soplo y "
                     "el dorso y no pudimos confirmarlo. Esta vez no hubo cachalotes.",
        "intro": "Una mañana de avistamiento de cetáceos en la costa oeste de La Palma, saliendo desde el puerto de "
                 "Tazacorte. Aquí tenéis el resumen de la salida y, al final, la lista completa de lo que registramos.",
        "summary": "Calderones tropicales con sus crías, delfines mulares y una tortuga boba para cerrar: {n} especies "
                   "registradas en una sola mañana. Gracias por compartir la salida con nosotros y esperamos veros pronto "
                   "de nuevo en el mar.",
        "titles": ["Avistamiento de cetáceos · salida de mañana", "Avistamiento de cetáceos · salida de tarde",
                   "Salida privada de avistamiento"],
        "places": ["Frente a Tazacorte", "Puerto Naos", "El Remo", "Frente a Las Manchas", "Punta de Fuencaliente"],
        "targets": "Calderón tropical, Cachalote, Rorcual tropical, Tortuga boba, Delfín moteado del Atlántico",
    },
    "en": {
        "title": "Whale & Dolphin Watching · Morning Trip",
        "place": "Off Tazacorte",
        "notes": "Morning trip from Tazacorte harbour (west coast), 18 guests. Calm sea, light haze. 20 min out big group "
                 "of pilot whales, about 25 with several calves, resting at the surface, came close to the boat very "
                 "relaxed. Then bottlenose x8 joining the pilot whales! Cory's shearwaters everywhere, lots sitting on the "
                 "water. On the way back a loggerhead turtle!! feeding on jellyfish near the surface. Possible Cuvier's "
                 "beaked whale very far, just a blow and the back, not confirmed. No sperm whales today.",
        "narrative": "We left Tazacorte harbour with 18 guests on a calm sea under a light haze. Twenty minutes out we "
                     "found a large group of about 25 short-finned pilot whales, with several calves, resting at the "
                     "surface; they came close to the boat completely relaxed. Soon after, eight common bottlenose "
                     "dolphins joined the pilot whales, a lovely encounter.\n\n"
                     "Cory's shearwaters were with us throughout the trip, many of them sitting on the water. On the way "
                     "back came the moment of the day: a loggerhead sea turtle feeding on jellyfish near the surface. Far "
                     "off we also saw what was probably a Cuvier's beaked whale, although only a blow and its back showed "
                     "and we could not confirm it. There were no sperm whales this time.",
        "intro": "A morning of whale and dolphin watching on the west coast of La Palma, setting out from Tazacorte "
                 "harbour. Here is the story of the trip, with the full list of everything we recorded at the end.",
        "summary": "Short-finned pilot whales with their calves, bottlenose dolphins and a loggerhead turtle to finish: "
                   "{n} species recorded in a single morning. Thank you for sharing the trip with us, and we hope to see "
                   "you out at sea again soon.",
        "titles": ["Whale & Dolphin Watching · Morning Trip", "Whale & Dolphin Watching · Afternoon Trip",
                   "Private Whale Watching Charter"],
        "places": ["Off Tazacorte", "Puerto Naos", "El Remo", "Off Las Manchas", "Fuencaliente Point"],
        "targets": "Short-finned Pilot Whale, Sperm Whale, Bryde's Whale, Loggerhead Sea Turtle, Atlantic Spotted Dolphin",
    },
}

# key, chance by month (Jan..Dec) or all year, count range, chance it stays unconfirmed, highlight?
POOL = [
    ("gma", .8, (8, 40), 0, False),
    ("ttr", .55, (4, 20), 0, False),
    ("sfr", [.05, .05, .1, .3, .6, .7, .75, .75, .6, .35, .1, .05], (10, 80), 0, False),
    ("dde", [.5, .5, .45, .3, .1, .05, .05, .05, .1, .2, .4, .5], (15, 150), 0, False),
    ("ggr", .12, (3, 15), 0, False),
    ("sbr", .06, (4, 15), .2, False),
    ("pma", [.08, .1, .15, .18, .2, .18, .15, .12, .1, .08, .06, .06], (1, 3), 0, True),
    ("bed", [0, 0, .02, .05, .15, .3, .35, .35, .3, .15, .05, 0], (1, 2), .1, True),
    ("bph", [.02, .08, .15, .15, .08, .02, 0, 0, 0, 0, 0, .01], (1, 2), .2, True),
    ("mno", [.03, .04, .03, 0, 0, 0, 0, 0, 0, 0, .01, .02], (1, 2), 0, True),
    ("oor", .01, (2, 6), 0, True),
    ("zca", .06, (1, 4), .4, True),
    ("mde", .04, (1, 3), .4, True),
    ("cca", [.3, .3, .35, .35, .4, .45, .45, .45, .4, .35, .3, .3], (1, 2), 0, False),
    ("cbo", [0, .02, .4, .8, .9, .9, .9, .9, .85, .6, .2, 0], (10, 200), 0, False),
    ("shi", [0, 0, .1, .3, .4, .4, .3, .25, .1, 0, 0, 0], (2, 12), 0, False),
    ("mmo", .04, (1, 1), 0, False),
    ("mmb", [0, 0, 0, 0, .03, .08, .1, .1, .06, 0, 0, 0], (1, 3), 0, False),
]


def _lang(org: Organization) -> str:
    return "es" if org.report_lang == "es" else "en"


def _sighting(lang: str, key: str, count, position: int, **kw) -> Sighting:
    en, es, sci, group = SP[key]
    kw = {"heard": False, "sure": True, "star": False, **kw}
    return Sighting(name=es if lang == "es" else en, sci=sci, count=count, position=position,
                    group=group_label(group, lang), taxon_status="matched", **kw)


def build_marine_trip(lang: str, guide: str = "") -> Trip:
    """The finished example outing (unsaved; also used for the public example page)."""
    lang = "es" if lang == "es" else "en"
    X = EX[lang]
    day = date.today() - timedelta(days=5)
    t = Trip(title=X["title"], location=LOCATION[lang], start_date=day, guests=18,
             guides=guide or "Laura y Dani" if lang == "es" else guide or "Laura and Dani",
             is_demo=True, lang=lang)
    d = Day(position=0, date=day, place=X["place"], notes=X["notes"], narrative=X["narrative"], approved=True,
            approved_by=guide or "Laura")
    rows = [("gma", 25, {"star": True}), ("ttr", 8, {}), ("cbo", None, {}), ("cca", 1, {"star": True}),
            ("zca", None, {"sure": False})]
    d.sightings = [_sighting(lang, k, c, i, **kw) for i, (k, c, kw) in enumerate(rows)]
    names = {s.sci: s.name for s in d.sightings}
    # where they were seen, off Tazacorte (the order and times follow the notes)
    for lat, lon, sci, hm, pre in [(28.6521, -17.9853, "Globicephala macrorhynchus", (10, 36), ""),
                                   (28.6284, -17.9921, "Tursiops truncatus", (11, 14), ""),
                                   (28.6447, -17.9690, "Caretta caretta", (12, 15), ""),
                                   (28.6402, -17.9575, "Ziphius cavirostris", (12, 28), "?")]:
        label = names[sci] + (" ?" if pre else "")
        d.points.append(Point(lat=lat, lon=lon, label=label, accuracy=8,
                              at=datetime(day.year, day.month, day.day, *hm, tzinfo=timezone.utc)))
    t.days.append(d)
    t.intro, t.summary = X["intro"], X["summary"].format(n=len(rows))
    return t


def add_marine_example(db: Session, org: Organization, user_id: str | None, guide: str) -> Trip:
    t = build_marine_trip(_lang(org), guide)
    t.org_id, t.created_by = org.id, user_id
    db.add(t)
    db.commit()
    return t


def add_marine_season(db: Session, org: Organization, user_id: str | None, guide: str, n: int = 90) -> int:
    """A year of single-day outings with Canary Islands seasonality (spotted dolphins in summer, common dolphins
    in winter, Bryde's whales in summer and autumn, shearwaters from March to October...)."""
    lang = _lang(org)
    X = EX[lang]
    r = random.Random(20261028)
    today = date.today()
    for i in range(n):
        day = today - timedelta(days=8 + int(i * 360 / n) + r.randint(0, 2))
        m = day.month - 1
        t = Trip(org_id=org.id, title=X["titles"][0 if r.random() < .65 else (1 if r.random() < .85 else 2)],
                 location=LOCATION[lang], start_date=day, guests=6 + int(r.random() * 25),
                 guides=guide or "Laura", is_demo=True, created_by=user_id)
        d = Day(position=0, date=day, place=r.choice(X["places"]), approved=True)
        pos = 0
        for key, p, (lo, hi), unsure_p, star in POOL:
            prob = p[m] if isinstance(p, list) else p
            if r.random() < prob:
                unsure = r.random() < unsure_p
                d.sightings.append(_sighting(lang, key, lo + int(r.random() * (hi - lo + 1)), pos,
                                             sure=not unsure, star=star and not unsure))
                pos += 1
        t.days.append(d)
        db.add(t)
    lynx_targets = ("Lince ibérico, Águila imperial ibérica, Búho real, Buitre negro",
                    "Iberian Lynx, Spanish Imperial Eagle, Eurasian Eagle-Owl, Cinereous Vulture")
    if not org.targets or org.targets in lynx_targets:
        org.targets = X["targets"]
    db.commit()
    return n
