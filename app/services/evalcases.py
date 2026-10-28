"""Messy field notes with the answer a careful human would give. The Admin accuracy page runs them
against the live AI, so any change of model or prompt can be measured instead of guessed.

expect: species that must be found -> {"sci": accepted scientific names, "count": number or None
        (None = no count may be invented; "any" = don't check), "sure": False if it must stay unconfirmed,
        "star": True if it must be a highlight}
absent: scientific names that must NOT appear (the guide said they weren't seen)
"""
from __future__ import annotations

CASES = [
    {
        "id": "cetaceos-la-palma", "lang": "es", "title": "Cetáceos, notas dictadas",
        "tally": "unos veinte calderones tropicales, delfines mulares por ocho, tortuga boba!, "
                 "muchas pardelas cenicientas, posible zifio?",
        "notes": "salida de mañana con mar en calma al principio luego algo de mar de fondo. los calderones "
                 "estaban descansando cerca de la costa con varias crías. no vimos cachalotes hoy",
        "expect": [
            {"sci": ["Globicephala macrorhynchus"], "count": 20},
            {"sci": ["Tursiops truncatus"], "count": 8},
            {"sci": ["Caretta caretta"], "count": "any", "star": True},
            {"sci": ["Calonectris borealis", "Calonectris diomedea"], "count": None},
            {"sci": ["Ziphius cavirostris", ""], "count": "any", "sure": False},
        ],
        "absent": ["Physeter macrocephalus"],
    },
    {
        "id": "errores-dictado", "lang": "es", "title": "Errores de dictado y correcciones",
        "tally": "vimos un cacha lote enorme y luego tres no cuatro delfines moteados una tortuga voba "
                 "y un par de alcatraces",
        "notes": "",
        "expect": [
            {"sci": ["Physeter macrocephalus"], "count": "any"},
            {"sci": ["Stenella frontalis"], "count": 4},
            {"sci": ["Caretta caretta"], "count": "any"},
            {"sci": ["Morus bassanus"], "count": 2},
        ],
        "absent": [],
    },
    {
        "id": "solo-notas", "lang": "es", "title": "Especies solo en las notas",
        "tally": "",
        "notes": "Salimos a las 9:30 con mar de fondo. A media mañana apareció un grupo de unos quince delfines "
                 "comunes que se acercaron a la proa. Más tarde, dos rorcuales tropicales alimentándose. "
                 "No hubo suerte con los cachalotes. Gasoil: repostar mañana.",
        "expect": [
            {"sci": ["Delphinus delphis"], "count": 15},
            {"sci": ["Balaenoptera edeni", "Balaenoptera brydei"], "count": 2},
        ],
        "absent": ["Physeter macrocephalus"],
    },
    {
        "id": "negaciones", "lang": "es", "title": "Negaciones",
        "tally": "ni rastro de la orca, sin cachalotes, solo calderones tropicales unos 25",
        "notes": "",
        "expect": [{"sci": ["Globicephala macrorhynchus"], "count": 25}],
        "absent": ["Orcinus orca", "Physeter macrocephalus"],
    },
    {
        "id": "dudas-es", "lang": "es", "title": "Dudas y cantidades",
        "tally": "calderones grises unos doce, perdón, catorce; creo que un delfín listado; varias gaviotas patiamarillas",
        "notes": "",
        "expect": [
            {"sci": ["Grampus griseus"], "count": 14},
            {"sci": ["Stenella coeruleoalba"], "count": "any", "sure": False},
            {"sci": ["Larus michahellis"], "count": None, "sure": True},
        ],
        "absent": [],
    },
    {
        "id": "birding-andujar", "lang": "en", "title": "Birding, typed fast",
        "tally": "40 grifons, 6 black vultures, imperial eagle pair!, links x1, heard eagle owl, no otters today, "
                 "maybe a bonellis eagle",
        "notes": "",
        "expect": [
            {"sci": ["Gyps fulvus"], "count": 40},
            {"sci": ["Aegypius monachus"], "count": 6},
            {"sci": ["Aquila adalberti"], "count": 2, "star": True},
            {"sci": ["Lynx pardinus"], "count": 1},
            {"sci": ["Bubo bubo"], "count": "any"},
            {"sci": ["Aquila fasciata"], "count": "any", "sure": False},
        ],
        "absent": ["Lutra lutra"],
    },
    {
        "id": "no-punctuation", "lang": "en", "title": "No punctuation, counts after names",
        "tally": "griffon vulture 40 black vulture 6 hoopoe 3 bee eaters lots azure winged magpies 12",
        "notes": "",
        "expect": [
            {"sci": ["Gyps fulvus"], "count": 40},
            {"sci": ["Aegypius monachus"], "count": 6},
            {"sci": ["Upupa epops"], "count": 3},
            {"sci": ["Merops apiaster"], "count": None},
            {"sci": ["Cyanopica cooki", "Cyanopica cyanus"], "count": 12},
        ],
        "absent": [],
    },
    {
        "id": "mixed-language", "lang": "en", "title": "English and Spanish mixed",
        "tally": "pilot whales x30, delfines mulares 5, a loggerhead turtle!, cory's shearwaters loads",
        "notes": "pilot whales were short-finned, logging at the surface",
        "expect": [
            {"sci": ["Globicephala macrorhynchus"], "count": 30},
            {"sci": ["Tursiops truncatus"], "count": 5},
            {"sci": ["Caretta caretta"], "count": "any", "star": True},
            {"sci": ["Calonectris borealis", "Calonectris diomedea"], "count": None},
        ],
        "absent": [],
    },
    {
        "id": "vague", "lang": "en", "title": "Vague names stay vague",
        "tally": "some kind of warbler, an eagle too far to tell, 3 hoopoes",
        "notes": "",
        "expect": [{"sci": ["Upupa epops"], "count": 3}],
        "absent": [],
        "vague_ok": True,  # extra rows are fine only if unconfirmed and without a scientific name
    },
    {
        "id": "salida-completa", "lang": "es", "title": "Salida completa dictada",
        "tally": "",
        "notes": "Salida de las 10 con 22 personas. Mar de fondo del noroeste, algo de viento. A la media hora "
                 "encontramos un grupo de calderones tropicales, serán unos 15 con 3 crías, muy tranquilos, se acercaron "
                 "al barco. Luego un cachalote macho solo, vimos la cola al sumergirse! Más tarde delfines comunes, "
                 "muchísimos, más de 100, saltando. De vuelta una tortuga verde. No vimos delfines mulares hoy.",
        "expect": [
            {"sci": ["Globicephala macrorhynchus"], "count": 15},
            {"sci": ["Physeter macrocephalus"], "count": "any"},
            {"sci": ["Delphinus delphis"], "count": 100},
            {"sci": ["Chelonia mydas"], "count": "any"},
        ],
        "absent": ["Tursiops truncatus"],
    },
    {
        "id": "correccion-especie", "lang": "es", "title": "Corrección de especie",
        "tally": "un zifio, perdón, era un cachalote; 6 delfines moteados",
        "notes": "",
        "expect": [
            {"sci": ["Physeter macrocephalus"], "count": "any"},
            {"sci": ["Stenella frontalis"], "count": 6},
        ],
        "absent": ["Ziphius cavirostris"],
    },
    {
        "id": "oidos", "lang": "es", "title": "Solo oídos",
        "tally": "de noche se oyeron pardelas cenicientas; 2 tortugas bobas",
        "notes": "",
        "expect": [
            {"sci": ["Calonectris borealis", "Calonectris diomedea"], "count": None, "heard": True},
            {"sci": ["Caretta caretta"], "count": 2},
        ],
        "absent": [],
    },
    {
        "id": "ranges", "lang": "en", "title": "Ranges and rough numbers",
        "tally": "4 or 5 bottlenose, 10-12 spotted dolphins, a few common dolphins",
        "notes": "",
        "expect": [
            {"sci": ["Tursiops truncatus"], "count": "any"},
            {"sci": ["Stenella frontalis"], "count": "any"},
            {"sci": ["Delphinus delphis"], "count": None},
        ],
        "absent": [],
    },
    {
        "id": "beaked-whales", "lang": "en", "title": "Beaked whales and doubt",
        "tally": "Blainvilles beaked whale x2 briefly, possible Cuviers too, no sperm whales",
        "notes": "",
        "expect": [
            {"sci": ["Mesoplodon densirostris"], "count": 2},
            {"sci": ["Ziphius cavirostris"], "count": "any", "sure": False},
        ],
        "absent": ["Physeter macrocephalus"],
    },
]


def by_id(case_id: str) -> dict | None:
    return next((c for c in CASES if c["id"] == case_id), None)


def _n(s: str) -> str:
    return " ".join((s or "").lower().split())


def score(case: dict, rows: list[dict]) -> dict:
    """Compare rows with the expected answer. Returns a dict with pass/fail and the reasons."""
    problems, used = [], set()
    for exp in case["expect"]:
        names = {_n(x) for x in exp["sci"] if x}
        hit = next((i for i, r in enumerate(rows) if i not in used and _n(r.get("sci")) in names), None)
        if hit is None and "" in exp["sci"]:  # an unconfirmed row without a scientific name is acceptable
            hit = next((i for i, r in enumerate(rows) if i not in used and not r.get("sci") and not r.get("sure")), None)
        if hit is None:
            problems.append(f"missing {exp['sci'][0] or 'unconfirmed row'}")
            continue
        used.add(hit)
        r = rows[hit]
        if exp.get("count", "any") != "any" and r.get("count") != exp["count"]:
            problems.append(f"{exp['sci'][0]}: count {r.get('count')} (expected {exp['count']})")
        if exp.get("sure") is False and r.get("sure"):
            problems.append(f"{exp['sci'][0]}: should be unconfirmed")
        if exp.get("sure") is True and not r.get("sure"):
            problems.append(f"{exp['sci'][0]}: should be confirmed")
        if exp.get("heard") and not r.get("heard"):
            problems.append(f"{exp['sci'][0]}: should be heard only")
        if exp.get("star") and not r.get("star"):
            problems.append(f"{exp['sci'][0]}: should be a highlight")
    absent = {_n(x) for x in case.get("absent", [])}
    for i, r in enumerate(rows):
        if _n(r.get("sci")) in absent:
            problems.append(f"{r.get('name')}: the guide said it was NOT seen")
        elif i not in used:
            if case.get("vague_ok") and not r.get("sci") and not r.get("sure"):
                continue
            problems.append(f"extra row: {r.get('name')}")
    expected = len(case["expect"])
    found = len(used)
    return {"ok": not problems, "found": found, "expected": expected, "problems": problems}
