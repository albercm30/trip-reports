"""Example content so a new operator sees a finished report and a full insights page in seconds."""
from __future__ import annotations

import random
from datetime import date, timedelta

from sqlalchemy.orm import Session

from ..models import Day, Organization, Sighting, Trip
from .reportdata import group_label

SCI = {"lynx": "Lynx pardinus", "deer": "Cervus elaphus", "mouf": "Ovis gmelini musimon", "mong": "Herpestes ichneumon",
       "imp": "Aquila adalberti", "gold": "Aquila chrysaetos", "bon": "Aquila fasciata", "grif": "Gyps fulvus",
       "cin": "Aegypius monachus", "king": "Alcedo atthis", "mag": "Cyanopica cooki", "hawf": "Coccothraustes coccothraustes",
       "owl": "Bubo bubo", "crag": "Ptyonoprogne rupestris", "sard": "Curruca melanocephala"}
MAMMALS = {"lynx", "deer", "mouf", "mong", "boar", "otter"}

EX = {
    "en": {
        "title": "Iberian Lynx Weekend",
        "intro": "Three days in the Sierra de Andújar, in the heart of Iberian lynx country: frosty mornings, oak-covered hills and long, patient hours at the viewpoints. Here is our Iberian Lynx Weekend, day by day, with the full list of everything we recorded at the end.",
        "d1": "We met at the hotel at eight under a clear, frosty sky and drove straight to the Encinarejo dam, where the Jándula river winds through the oak-covered hills. The ridge above us was soon busy with vultures, dozens of griffons with a handful of the huge cinereous vultures among them, and just before eleven a pair of Spanish imperial eagles began displaying overhead.\n\nAfter a riverside picnic, with a kingfisher flashing past more than once, we settled in at the lynx viewpoints for the long afternoon wait. At 18:40 María spotted a young Iberian lynx walking along the far bank. We followed it through the scopes for six unforgettable minutes before it slipped into the scrub, and the quiet celebrations lasted all the way back to the car, with red deer stags roaring in the dusk.",
        "d2": "An early start rewarded us before sunrise with the deep call of an eagle-owl close to the track. The lynx stayed hidden today despite five patient hours at the viewpoint, but the hills were far from empty: a herd of mouflon picked its way across the rocky slope, azure-winged magpies moved through the oaks in noisy groups, and a few hawfinches showed well in the treetops.\n\nHigh above the ridge we watched a large eagle that was probably a Bonelli's eagle, though it stayed too distant to be certain. When the rain arrived after lunch we called it a day and warmed up with hot chocolate in the village.",
        "d3": "Our last morning brought the finale everyone had hoped for. From the viewpoint over the upper Jándula valley we found a female Iberian lynx with a well-grown kitten resting on a sunny rock, and watched them groom and doze for nearly twenty minutes.\n\nOn the way back down an Egyptian mongoose trotted across the track, and a golden eagle drifted along the ridge while crag martins hunted around the cliffs. We finished with a relaxed lunch in Andújar, adding up a trip list none of us will forget in a hurry.",
        "summary": "Looking back, it's hard to beat Iberian lynx on two of our three days, including a mother and kitten on the final morning. Add a displaying pair of Spanish imperial eagles, great numbers of vultures and a pre-dawn eagle-owl, and it was a weekend to remember, with {n} species recorded in total. Thank you all for your patience, sharp eyes and good company.",
        "names": {"lynx": "Iberian Lynx", "deer": "Red Deer", "mouf": "Mouflon", "mong": "Egyptian Mongoose", "imp": "Spanish Imperial Eagle",
                  "gold": "Golden Eagle", "bon": "Bonelli's Eagle", "grif": "Griffon Vulture", "cin": "Cinereous Vulture",
                  "king": "Common Kingfisher", "mag": "Iberian Magpie", "hawf": "Hawfinch", "owl": "Eurasian Eagle-Owl",
                  "crag": "Eurasian Crag Martin", "sard": "Sardinian Warbler"},
    },
    "es": {
        "title": "Fin de semana del lince",
        "intro": "Tres días en la Sierra de Andújar, en pleno territorio del lince ibérico: mañanas de escarcha, colinas cubiertas de encinas y largas horas de paciencia en los miradores. Este es nuestro Fin de semana del lince, día a día, con la lista completa de todo lo que registramos al final.",
        "d1": "Nos encontramos en el hotel a las ocho, con el cielo despejado y escarcha, y fuimos directos a la presa del Encinarejo, donde el río Jándula serpentea entre las encinas. La cresta sobre nosotros se llenó pronto de buitres, decenas de leonados con algunos enormes buitres negros entre ellos, y poco antes de las once una pareja de águilas imperiales ibéricas empezó a hacer vuelos de cortejo sobre nuestras cabezas.\n\nTras un picnic junto al río, con un martín pescador pasando como un rayo más de una vez, nos instalamos en los miradores del lince para la larga espera de la tarde. A las 18:40 María localizó un lince ibérico joven caminando por la orilla opuesta. Lo seguimos con los telescopios durante seis minutos inolvidables antes de que se metiera en el matorral, y la celebración en voz baja duró hasta el coche, con los ciervos berreando al anochecer.",
        "d2": "Madrugar tuvo premio: antes del amanecer escuchamos el canto grave de un búho real muy cerca del camino. El lince no se dejó ver a pesar de cinco horas de paciencia en el mirador, pero el monte estaba lleno de vida: un grupo de muflones cruzó la ladera rocosa, los rabilargos recorrían las encinas en bandos ruidosos y varios picogordos se dejaron ver bien en las copas.\n\nMuy alto sobre la cresta observamos un águila grande que probablemente era un águila perdicera, aunque estaba demasiado lejos para confirmarlo. Cuando llegó la lluvia después de comer, terminamos el día con un chocolate caliente en el pueblo.",
        "d3": "La última mañana nos dio el final que todos esperábamos. Desde el mirador sobre el alto Jándula encontramos una hembra de lince ibérico con un cachorro ya crecido descansando al sol sobre una roca, y los vimos acicalarse y dormitar durante casi veinte minutos.\n\nDe bajada, un meloncillo cruzó el camino al trote y un águila real planeó a lo largo de la cresta mientras los aviones roqueros cazaban junto a los cortados. Terminamos con una comida tranquila en Andújar, repasando una lista que ninguno olvidará fácilmente.",
        "summary": "Mirando atrás, es difícil superar ver lince ibérico en dos de nuestros tres días, incluida una hembra con su cachorro la última mañana. Si sumamos una pareja de imperiales en cortejo, muchísimos buitres y un búho real antes del amanecer, fue un fin de semana para recordar, con {n} especies registradas en total. Gracias a todos por vuestra paciencia, vuestros buenos ojos y la buena compañía.",
        "names": {"lynx": "Lince ibérico", "deer": "Ciervo", "mouf": "Muflón", "mong": "Meloncillo", "imp": "Águila imperial ibérica",
                  "gold": "Águila real", "bon": "Águila perdicera", "grif": "Buitre leonado", "cin": "Buitre negro",
                  "king": "Martín pescador", "mag": "Rabilargo", "hawf": "Picogordo", "owl": "Búho real",
                  "crag": "Avión roquero", "sard": "Curruca cabecinegra"},
    },
}

NOTES = {
    "en": {
        1: "Met group 8am. Cold, clear sky, frost on the car. Encinarejo dam all morning. Loads of vultures on the ridge, few black vultures. Imperial eagle pair displaying ~11. Picnic by river, kingfisher kept flying past. Afternoon at lynx viewpoints. 18:40 María spotted young lynx on far bank ~300m, 6 min in scopes then into the bushes!! Stags roaring at dusk.",
        2: "Start before sunrise, eagle owl calling near the track. No lynx, 5 hrs at viewpoint. Mouflon herd on rocky slope. Azure-winged magpies, few hawfinches. Probable Bonelli's very high over the ridge, too far. Rain after lunch, hot chocolate in village.",
        3: "Last morning. Female lynx + big kitten on sunny rock, ~20 min grooming and dozing!! Mongoose crossed track on way down. Golden eagle along ridge, crag martins hunting at the cliffs. Lunch in Andújar.",
    },
    "es": {
        1: "Quedamos 8h en el hotel. Frío, cielo despejado, escarcha en el coche. Presa del Encinarejo toda la mañana. Muchos buitres en la cresta, algunos negros. Pareja de imperiales en cortejo hacia las 11. Picnic junto al río, el martín pescador pasando todo el rato. Tarde en los miradores del lince. 18:40 María ve un lince joven en la otra orilla a unos 300 m, 6 min con los telescopios y se mete en el matorral!! Ciervos berreando al anochecer.",
        2: "Salida antes del amanecer, búho real cantando cerca del camino. Sin lince, 5 h en el mirador. Grupo de muflones en la ladera rocosa. Rabilargos, algunos picogordos. Probable perdicera muy alta sobre la cresta, demasiado lejos. Lluvia después de comer, chocolate caliente en el pueblo.",
        3: "Última mañana. Hembra de lince + cachorro grande en una roca al sol, unos 20 min acicalándose y dormitando!! Meloncillo cruza el camino al bajar. Águila real por la cresta, aviones roqueros cazando en los cortados. Comida en Andújar.",
    },
}
PLACE_NAMES = {
    "en": {1: "Encinarejo dam and Jándula river", 2: "La Lastrilla track", 3: "Upper Jándula valley"},
    "es": {1: "Presa del Encinarejo y río Jándula", 2: "Camino de La Lastrilla", 3: "Alto Jándula"},
}
LOCATION = {"en": "Sierra de Andújar, Jaén, Spain", "es": "Sierra de Andújar, Jaén, España"}


def _lang(org: Organization) -> str:
    return "es" if org.report_lang == "es" else "en"


def _sighting(lang: str, key: str, count, **kw) -> Sighting:
    kw = {"heard": False, "sure": True, "star": False, **kw}
    return Sighting(name=EX[lang]["names"][key], sci=SCI[key], count=count,
                    group=group_label("mammals" if key in MAMMALS else "birds", lang if lang in ("en", "es") else "en"),
                    taxon_status="matched", **kw)


def add_example_trip(db: Session, org: Organization, user_id: str | None, guide: str) -> Trip:
    t = build_example_trip(_lang(org), guide)
    t.org_id, t.created_by = org.id, user_id
    db.add(t)
    db.commit()
    return t


def build_example_trip(lang: str, guide: str = "") -> Trip:
    """An unsaved example trip (also used for the public example report)."""
    lang = "es" if lang == "es" else "en"
    X = EX[lang]
    start = date.today() - timedelta(days=12)
    t = Trip(title=X["title"], location=LOCATION[lang], start_date=start, guests=6,
             guides=guide or "Alberto", is_demo=True, intro="", summary="")
    specs = {
        1: (PLACE_NAMES[lang][1], X["d1"], [("lynx", 1, {"star": True}), ("deer", 35, {}), ("imp", 2, {"star": True}),
                                                          ("grif", 60, {}), ("cin", 8, {}), ("king", 1, {}), ("mag", 20, {})]),
        2: (PLACE_NAMES[lang][2], X["d2"], [("owl", None, {"heard": True}), ("mouf", 12, {}), ("mag", 25, {}), ("hawf", 3, {}),
                                            ("bon", 1, {"sure": False}), ("cin", 2, {}), ("grif", 30, {})]),
        3: (PLACE_NAMES[lang][3], X["d3"], [("lynx", 2, {"star": True}), ("mong", 1, {}), ("gold", 1, {}), ("crag", 15, {}),
                                              ("deer", 18, {}), ("grif", 25, {}), ("sard", 4, {})]),
    }
    for n, (place, narrative, sp) in specs.items():
        d = Day(position=n - 1, date=start + timedelta(days=n - 1), place=place, notes=NOTES[lang][n], narrative=narrative,
                approved=True, approved_by=guide or "Alberto")
        d.sightings = [_sighting(lang, k, c, position=i, **kw) for i, (k, c, kw) in enumerate(sp)]
        t.days.append(d)
    n_species = len({s.sci for d in t.days for s in d.sightings})
    t.intro, t.summary = X["intro"], X["summary"].format(n=n_species)
    return t


# key, English, Spanish, sci, group, chance per day (number or by month), count range, heard-only chance
POOL = [
    ("lynx", "Iberian Lynx", "Lince ibérico", "Lynx pardinus", "m", [.55, .5, .4, .3, .25, .2, .15, .15, .2, .3, .35, .5], (1, 2), 0),
    ("deer", "Red Deer", "Ciervo", "Cervus elaphus", "m", .95, (8, 45), 0),
    ("mouf", "Mouflon", "Muflón", "Ovis gmelini musimon", "m", .45, (3, 15), 0),
    ("boar", "Wild Boar", "Jabalí", "Sus scrofa", "m", .3, (1, 8), 0),
    ("mong", "Egyptian Mongoose", "Meloncillo", "Herpestes ichneumon", "m", .18, (1, 3), 0),
    ("otter", "Eurasian Otter", "Nutria", "Lutra lutra", "m", .1, (1, 2), 0),
    ("imp", "Spanish Imperial Eagle", "Águila imperial ibérica", "Aquila adalberti", "b", .5, (1, 3), 0),
    ("gold", "Golden Eagle", "Águila real", "Aquila chrysaetos", "b", .3, (1, 2), 0),
    ("bon", "Bonelli's Eagle", "Águila perdicera", "Aquila fasciata", "b", .12, (1, 2), 0),
    ("grif", "Griffon Vulture", "Buitre leonado", "Gyps fulvus", "b", .98, (15, 90), 0),
    ("cin", "Cinereous Vulture", "Buitre negro", "Aegypius monachus", "b", .8, (2, 15), 0),
    ("egv", "Egyptian Vulture", "Alimoche", "Neophron percnopterus", "b", [0, 0, .3, .5, .5, .5, .5, .5, .4, 0, 0, 0], (1, 3), 0),
    ("ste", "Short-toed Snake Eagle", "Culebrera europea", "Circaetus gallicus", "b", [0, 0, .3, .6, .6, .6, .6, .6, .4, 0, 0, 0], (1, 2), 0),
    ("boot", "Booted Eagle", "Aguililla calzada", "Hieraaetus pennatus", "b", [0, 0, .3, .5, .5, .5, .5, .5, .4, .1, 0, 0], (1, 3), 0),
    ("bst", "Black Stork", "Cigüeña negra", "Ciconia nigra", "b", [0, .1, .3, .35, .35, .35, .3, .3, .3, .1, 0, 0], (1, 3), 0),
    ("owl", "Eurasian Eagle-Owl", "Búho real", "Bubo bubo", "b", .22, (1, 2), .7),
    ("mag", "Iberian Magpie", "Rabilargo", "Cyanopica cooki", "b", .95, (6, 40), 0),
    ("hoop", "Eurasian Hoopoe", "Abubilla", "Upupa epops", "b", .6, (1, 5), 0),
    ("bee", "European Bee-eater", "Abejaruco", "Merops apiaster", "b", [0, 0, 0, .6, .9, .9, .9, .8, .4, 0, 0, 0], (5, 40), 0),
    ("hawf", "Hawfinch", "Picogordo", "Coccothraustes coccothraustes", "b", [.5, .5, .35, .2, .15, .1, .1, .1, .15, .3, .45, .5], (1, 6), 0),
    ("brt", "Blue Rock Thrush", "Roquero solitario", "Monticola solitarius", "b", .4, (1, 2), 0),
    ("king", "Common Kingfisher", "Martín pescador", "Alcedo atthis", "b", .3, (1, 2), 0),
    ("sard", "Sardinian Warbler", "Curruca cabecinegra", "Curruca melanocephala", "b", .9, (2, 10), 0),
    ("crest", "Crested Tit", "Herrerillo capuchino", "Lophophanes cristatus", "b", .35, (1, 4), 0),
    ("crag", "Eurasian Crag Martin", "Avión roquero", "Ptyonoprogne rupestris", "b", .55, (4, 25), 0),
    ("rrs", "Red-rumped Swallow", "Golondrina dáurica", "Cecropis daurica", "b", [0, 0, .4, .7, .7, .7, .7, .7, .5, .1, 0, 0], (2, 12), 0),
    ("ori", "Eurasian Golden Oriole", "Oropéndola", "Oriolus oriolus", "b", [0, 0, 0, .2, .5, .5, .4, .3, .1, 0, 0, 0], (1, 3), .5),
    ("rbun", "Rock Bunting", "Escribano montesino", "Emberiza cia", "b", .45, (1, 6), 0),
    ("gwood", "Iberian Green Woodpecker", "Pito real ibérico", "Picus sharpei", "b", .45, (1, 2), .4),
    ("bwhe", "Black Wheatear", "Collalba negra", "Oenanthe leucura", "b", .15, (1, 2), 0),
]
PLACES = {"en": ["Encinarejo dam", "Jándula river", "La Lastrilla track", "Upper Jándula valley", "Santuario viewpoint",
                 "Los Escoriales", "Río Yeguas", "Cerro del Cabezo"],
          "es": ["Presa del Encinarejo", "Río Jándula", "Camino de La Lastrilla", "Alto Jándula", "Mirador del Santuario",
                 "Los Escoriales", "Río Yeguas", "Cerro del Cabezo"]}


def add_demo_season(db: Session, org: Organization, user_id: str | None, guide: str, n: int = 16) -> int:
    lang = _lang(org)
    r = random.Random(20260930)
    titles = (["Fin de semana del lince", "Lince y rapaces", "Aves de Sierra Morena", "Especial lince de invierno",
               "Rapaces y abejarucos de primavera"] if lang == "es" else
              ["Iberian Lynx Weekend", "Lynx and Raptors", "Sierra Morena Birding", "Winter Lynx Special",
               "Spring Raptors and Bee-eaters"])
    today = date.today()
    for i in range(n):
        start = today - timedelta(days=20 + round(i * 22 + r.random() * 8))
        m = start.month - 1
        nd = 2 if r.random() < .6 else 3
        if m in (0, 1, 11):
            title = titles[3]
        elif 3 <= m <= 6:
            title = titles[4] if r.random() < .5 else titles[2]
        else:
            title = titles[0] if r.random() < .5 else titles[1]
        t = Trip(org_id=org.id, title=title, location=LOCATION[lang], start_date=start,
                 guests=2 + int(r.random() * 7), guides=guide or "Alberto", is_demo=True, created_by=user_id)
        for di in range(nd):
            d = Day(position=di, date=start + timedelta(days=di), place=r.choice(PLACES[lang]), approved=True)
            pos = 0
            for key, en, es, sci, g, p, (lo, hi), heard_p in POOL:
                prob = p[m] if isinstance(p, list) else p
                if r.random() < prob:
                    heard = bool(heard_p) and r.random() < heard_p
                    d.sightings.append(Sighting(
                        sure=True, position=pos, name=es if lang == "es" else en, sci=sci,
                        count=None if heard else lo + int(r.random() * (hi - lo + 1)), heard=heard,
                        star=key in ("lynx", "imp"), taxon_status="matched",
                        group=group_label("mammals" if g == "m" else "birds", lang)))
                    pos += 1
            t.days.append(d)
        db.add(t)
    if not org.targets:
        org.targets = ("Lince ibérico, Águila imperial ibérica, Búho real, Buitre negro" if lang == "es" else
                       "Iberian Lynx, Spanish Imperial Eagle, Eurasian Eagle-Owl, Cinereous Vulture")
    db.commit()
    return n


def remove_demo(db: Session, org: Organization) -> int:
    trips = db.query(Trip).filter(Trip.org_id == org.id, Trip.is_demo.is_(True)).all()
    for t in trips:
        db.delete(t)
    db.commit()
    return len(trips)
