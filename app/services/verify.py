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

from .species import (DOUBT, GENERIC, VAGUE, supported_by, words_to_digits, Vocab, _prepare, default_vocab, norm, parse_entry, parse_tally,
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


def _raw_before(text: str, src: str) -> list[str]:
    """Up to 3 words right before the guide's words, stopping at punctuation (, ; . ! ? and new lines)."""
    t = strip_accents((text or "").lower())
    s = strip_accents((src or "").lower()).strip()
    i = t.find(s) if s else -1
    if i < 0:
        return []
    before = re.split(r"[,;.!?\n]", t[:i])[-1]
    return before.split()[-3:]


CORR_AFTER = re.compile(r"^[\s,.;:]*(perdon|digo|mejor dicho|sorry|i mean|no wait|wait no|actually|correction|"
                        r"no,? era|no,? es|no,? was)\b[\s,]*(era|es|was|it was|fue)?\s*(\S+)?", re.I)
NUMBER_WORD = re.compile(r"^(\d+|" + "|".join(sorted({"un", "uno", "una", "one", "two", "three", "four", "five", "six",
                         "seven", "eight", "nine", "ten", "dos", "tres", "cuatro", "cinco", "seis", "siete", "ocho",
                         "nueve", "diez", "once", "doce", "trece", "catorce", "quince", "veinte"}, key=len, reverse=True))
                         + r")$", re.I)


def _corrected_after(text: str, src: str) -> bool:
    t = strip_accents((text or "").lower())
    s = strip_accents((src or "").lower()).strip()
    i = t.find(s) if s else -1
    if i < 0:
        return False
    m = CORR_AFTER.match(t[i + len(s): i + len(s) + 40])
    if not m:
        return False
    nxt = (m.group(3) or "").strip(",.;")
    # "un zifio, perdón, era un cachalote" is a species correction; "doce, perdón, catorce" only a count
    if nxt in ("un", "una", "uno", "a", "an", "one"):
        return True
    return bool(nxt) and not NUMBER_WORD.match(nxt)


def _count_corrected_after(text: str, src: str) -> int | None:
    """"calderones grises unos doce, perdón, catorce" quoted only up to "doce": the guide's final number."""
    t = strip_accents((text or "").lower())
    s = strip_accents((src or "").lower()).strip()
    i = t.find(s) if s else -1
    if i < 0:
        return None
    m = CORR_AFTER.match(t[i + len(s): i + len(s) + 40])
    if not m or not m.group(3):
        return None
    n = re.match(r"\d+", words_to_digits(m.group(3).strip(",.;")))
    return int(n.group(0)) if n else None


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
        # 1b. the guide corrected the species right after ("un zifio, perdón, era un cachalote")
        if _corrected_after(text, src):
            changes.append(f"dropped {r['name']}: the guide corrected it to another species")
            continue
        # 2. the count must be in the guide's words for this species
        free = parse_entry(_prepare(src), vocab)
        nums = _numbers(src)
        corrected = _count_corrected_after(text, src)
        if corrected is not None:
            nums, free = {corrected}, dict(free or {}, count=corrected)
        if free and free.get("count") is not None and len(nums) <= 1 and r.get("count") != free["count"]:
            if r.get("count") is not None:
                changes.append(f"{r['name']}: count {r['count']} -> {free['count']} (from the guide's words)")
            r["count"] = free["count"]
        elif r.get("count") is not None and nums and r["count"] not in nums:
            changes.append(f"{r['name']}: count {r['count']} -> {max(nums)} (from the guide's words)")
            r["count"] = max(nums)
        elif r.get("count") is not None and r["count"] > 1 and not nums and not (free and free.get("count")):
            sentence_nums = _numbers(_sentence_at(text, src_n.split()[0] if src_n else ""))
            if r["count"] not in sentence_nums:
                changes.append(f"{r['name']}: removed count {r['count']}, the guide didn't give one")
                r["count"] = None
        # 3. doubt and highlights right where the guide wrote the name: "posible zifio?", "tortuga boba!"
        mi = _find(src_n, marks) if src_n else -1
        after = marks[mi + len(src_n): mi + len(src_n) + 12].split()[:1] if mi >= 0 else []
        doubt_before = idx >= 0 and DOUBT.search(" ".join(_raw_before(text, src)))
        if DOUBT.search(src) or "qmark" in after or doubt_before:
            r["sure"] = False
        if "!" in src or "xmark" in after:
            r["star"] = True
        # 4. if the guide literally wrote a species' name, that name wins over the model's guess
        if free and free.get("sci") and free.get("_entry") and r.get("sci") and norm(free["sci"]) != norm(r["sci"]) \
                and (free.get("sure") or (DOUBT.search(src) and _exact_name(free["_entry"], src, vocab))):
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
    # one name per species, the standard one, so reports and season statistics stay consistent
    if lang in ("en", "es"):
        for r in out:
            e = vocab.by_key.get(norm(r.get("sci") or "")) if r.get("sci") else None
            if e and e.get(lang) and norm(e.get("sci", "")) == norm(r["sci"]):
                r["name"] = e[lang]
    out = _merge(out)
    # 6. recall: species the free parser reads with certainty from the tally but the AI left out
    if tally.strip():
        have = {norm(x.get("sci") or "") for x in out if x.get("sci")} | {norm(x["name"]) for x in out}
        for f in parse_tally(tally, vocab, lang):
            if not f.get("sci"):
                # a doubted group name ("posible zifio?") the AI left out: keep it, unconfirmed, unless a row
                # already covers those words
                gn = sing_all(norm(f.get("name", "")))
                covered = any(supported_by(f.get("source", ""), x.get("source", "") or x.get("name", "")) or
                              supported_by(x.get("source", "") or x.get("name", ""), f.get("source", "")) for x in out)
                if gn in GENERIC and not f.get("sure") and not covered and gn not in have:
                    f.pop("_entry", None)
                    changes.append(f"added {f['name']} (unconfirmed), which the AI missed")
                    out.append(f)
                    have.add(gn)
                continue
            if not f.get("sure"):
                # unconfirmed only because the guide doubted it ("creo que un delfín listado"): add it, flagged;
                # unconfirmed because the name was a loose match: leave it out
                e = vocab.by_key.get(norm(f["sci"]))
                if not (e and _exact_name(e, f.get("source", ""), vocab)):
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
    from .species import FILLER, QUANTITY
    cleaned = " ".join(QUANTITY.sub(" ", FILLER.sub(" ", DOUBT.sub(" ", re.sub(r"\d+|\bx\b", " ", s)))).split())
    e, sc = vocab.match(cleaned) if cleaned else (None, 0)
    return bool(e and norm(e["sci"]) == norm(entry["sci"]) and sc >= 0.95)


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
            for k in {norm(n or ""), sing_all(norm(n or ""))}:
                if len(k) >= 4 and " " in k or len(k) >= 6:  # skip short one-word names that are common words
                    idx.setdefault(k, e)
    for tail, entries in vocab.tails.items():  # distinctive short English names: "hoopoe", "spoonbill"
        if len(entries) != 1 or len(tail) < 5 or " " in tail or tail in idx or tail in GENERIC:
            continue
        e = entries[0]
        others = sum(tail in sing_all(norm(f"{x.get('en', '')} {x.get('es', '')}")).split() or
                     tail in norm(f"{x.get('en', '')} {x.get('es', '')}").split() for x in vocab.entries)
        if norm(e.get("en", "")).split()[-1:] == [tail] and others == 1:
            idx[tail] = e  # e.g. "martin" is out: "martín pescador" is a kingfisher
    return idx


def _en_sing(w: str) -> str:
    if len(w) > 4 and w.endswith("ies"):
        return w[:-3] + "y"
    return w[:-1] if len(w) > 3 and w.endswith("s") and not w.endswith(("ss", "us", "is")) else w


_INDEX: dict[int, dict] = {}


def mentioned_species(text: str, vocab: Vocab | None = None) -> list[dict]:
    """Species from the vocabulary named in a piece of text (exact names, any language)."""
    vocab = vocab or default_vocab()
    index = _INDEX.get(id(vocab))
    if index is None:
        index = _INDEX[id(vocab)] = _names_index(vocab)
    base = norm(text)
    variants = [base.split(), sing_all(base).split(), [_en_sing(w) for w in base.split()]]
    found, seen = [], set()
    for words in variants:
        for n in (4, 3, 2, 1):
            for i in range(len(words) - n + 1):
                e = index.get(" ".join(words[i:i + n]))
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


# Details guests would read as facts. Each concept lists words in every language, so Spanish notes can
# support an English report. "x=" is a whole word, "x*" a word start (accents ignored).
CONCEPTS = {
    "water": "water* agua*",
    "sea": "sea= seas= ocean* mar= oceano*",
    "shore": "shore* coast* beach* orilla* costa= costas= playa* litoral*",
    "cliffs": "cliff* acantilad* cortados=",
    "forest": "forest* woodland* woods= bosque*",
    "sky": "sky= skies= cielo*",
    "river": "river* rio= rios=",
    "hills": "mountain* ridge* canyon* valley* hill* montan* cresta* canon* valle= valles= colina* loma*",
    "horizon": "horizon* horizonte*",
    "sun": "light= golden= sun= sunny= sunlight* sunshine* sunset* sunrise* sol= soleado* amanecer* atardecer* anochecer*",
    "wind": "wind= windy= breeze* viento* brisa*",
    "rain": "rain= rainy= raining= cloud* fog* mist= misty= lluvi* nube* nublad* niebla*",
    "sound": "call= calls= calling= called= song* sound* echo* hoot* llamad* canto= cantos= cantand* sonido* eco= ulul*",
    "jumping": "jump* leap* breach* splash* saltand* saltaron* saltaba* salto= saltos= brinc*",
    "playing": "play= playing= playful* frolic* jugand* juguet* jugaban*",
    "flying": "glid* soar* circl* flew= fly= flying= flies= flown= planeand* planeaba* planearon* sobrevol* volando= volaban= volaron= volaba=",
    "feeding": "feed* hunt* alimentand* alimentab* alimentar* cazand* cazaba*",
    "swimming": "swim* dive= dived= diving= nadand* nadaba* nadaron* buce* zambull* sumerg*",
    "perched": "perch* posad*",
    "approach": "approach* acerc*",
    "distance": "distance* distant* nearby= far= lejos= lejan* distancia* cerca=",
    "around us": "swarm* surround* rodea* enjambr*",
    "young": "calf= calves= juvenile* cria= crias= cachorro* juvenil*",
}
_CONCEPT_PATTERNS = [(name, [(w[:-1], w[-1]) for w in words.split()]) for name, words in CONCEPTS.items()]


def _concepts(text: str) -> dict[str, str]:
    """{concept: first word that expresses it} for a text."""
    found = {}
    for tok in re.findall(r"[a-z]+", strip_accents((text or "").lower())):
        for name, pats in _CONCEPT_PATTERNS:
            if name in found:
                continue
            for stem, kind in pats:
                if (kind == "=" and tok == stem) or (kind == "*" and tok.startswith(stem)):
                    found[name] = tok
                    break
    return found


HEARD_WORDS = re.compile(r"\b(heard|hear|hearing|calls?|calling|song|singing|escuch\w*|o[ií]mos|o[ií]do|o[ií]r|"
                         r"cant(o|aba|ando)|llamad\w*)\b", re.I)


def _mentions(sentence: str, s_, vocab: Vocab) -> bool:
    """Does the sentence name this species (its own name, its standard names, singular or plural)?"""
    sci = norm(getattr(s_, "sci", "") or "")
    if sci and any(norm(e["sci"]) == sci for e in mentioned_species(sentence, vocab)):
        return True
    keys = _variants(s_.name) if s_.name else set()
    if sci:
        for e in vocab.entries:
            if norm(e["sci"]) == sci:
                keys |= _variants(e["en"]) | _variants(e["es"])
    sv = _variants(sentence)
    return any(k and re.search(r"\b" + re.escape(k) + r"\b", v) for k in keys for v in sv)


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
    # weather, places, sounds and behaviour must come from the notes
    in_notes_c = _concepts(notes)
    if any(getattr(s_, "heard", False) for s_ in species) or HEARD_WORDS.search(notes or ""):
        in_notes_c["sound"] = "heard"  # a heard-only species can be described by its call
    for name, word in _concepts(text).items():
        if name not in in_notes_c:
            problems.append({"kind": "detail", "what": word})
    # only species heard (not seen) may be described as heard
    clauses = re.split(r"[.!?;,:]|\s(?:and|but|while|whereas|y|pero|mientras|aunque)\s", text)
    for sent in clauses:
        if not HEARD_WORDS.search(sent):
            continue
        for s_ in species:
            if getattr(s_, "heard", False) or not s_.name:
                continue
            if _mentions(sent, s_, vocab):
                problems.append({"kind": "heard", "what": s_.name})
    # a text that stops mid-sentence
    if not re.search(r"[.!?…»\"')]\s*$", text):
        problems.append({"kind": "format", "what": "cut"})
    # unconfirmed species must not be stated as certain
    for s in species:
        if getattr(s, "sure", True) or not s.name:
            continue
        for sent in re.split(r"(?<=[.!?])\s+", text):
            if _mentions(sent, s, vocab) and not HEDGE.search(sent):
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
        elif p["kind"] == "detail":
            lines.append(f"\"{p['what']}\" (a weather, place, sound or behaviour detail) is not in the notes. Remove it.")
        elif p["kind"] == "heard":
            lines.append(f"{p['what']} was seen, not heard. Don't say it was heard.")
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


def drop_false_claims(claims: list[dict], species: list, notes: str, lang: str,
                      allowed_numbers: set[int] | None = None) -> list[dict]:
    """The checking model sometimes flags a true fact because the notes use another name or a correction
    ("6 black vultures" vs "six Cinereous Vultures", "tres no cuatro" vs "cuatro"). A short quote that only
    names listed species, with numbers the code accepts, is kept as supported."""
    out = []
    listed = {norm(getattr(s, "sci", "") or "") for s in species} - {""}
    for c in claims:
        q = c.get("what") or c.get("quote") or ""
        named = [e for e in mentioned_species(q) if norm(e["sci"]) in listed] or \
            [s for s in species if s.name and sing_all(norm(s.name)) in sing_all(norm(q))]
        if named and len(q.split()) <= 7 and not check_text(q.rstrip(" .") + ".", lang=lang, species=species, notes=notes,
                                                              allowed_numbers=allowed_numbers):
            continue
        out.append(c)
    return out


def _variants(s: str) -> set[str]:
    base = norm(s)
    return {base, sing_all(base), " ".join(_en_sing(w) for w in base.split())}


def prune(text: str, problems: list[dict], species: list) -> tuple[str, list[dict]]:
    """Last resort after the rewrites: drop whole sentences that still carry an invented detail or claim,
    as long as the sentence doesn't name a species from the list (those need the guide's eye instead)."""
    bad = [p for p in problems if p["kind"] in ("detail", "claim")]
    if not bad:
        return text, problems
    listed_sci = {norm(getattr(s_, "sci", "") or "") for s_ in species} - {""}
    names = set()
    for s_ in species:
        for k in (getattr(s_, "name", ""), getattr(s_, "sci", "")):
            if k:
                names |= _variants(k)
    paras_out, removed = [], set()
    for para in re.split(r"\n\s*\n", text):
        keep = []
        for sent in re.split(r"(?<=[.!?])\s+", para.strip()):
            hits = [p for p in bad if p["what"].lower() in sent.lower()
                    or (p["kind"] == "detail" and re.search(r"\b" + re.escape(p["what"]) + r"\w*", strip_accents(sent.lower())))]
            sv = _variants(sent)
            names_species = any(norm(e["sci"]) in listed_sci for e in mentioned_species(sent)) or any(
                n and re.search(r"\b" + re.escape(n) + r"\b", v) for n in names for v in sv)
            if hits and not names_species:
                removed |= {id(p) for p in hits}
                continue
            keep.append(sent)
        if keep:
            paras_out.append(" ".join(keep))
    left = [p for p in problems if id(p) not in removed]
    return "\n\n".join(paras_out), left
