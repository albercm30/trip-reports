"""Turns a guide's rough tally into species rows without any AI service.

Handles typing and dictation: number words ("forty two", "cuarenta y dos"), "x2", "times two",
"a pair of", "heard", "?", "!", fillers ("um", "bueno"), quick corrections ("three no four"),
negations ("no lynx today"), runs without commas ("40 griffons 2 black vultures"), and
misspelt or mis-heard names, which are matched against a species dictionary with typo tolerance.

When an AI provider is configured it does this better; its rows are checked here too, so a
species that isn't in the guide's own words is never added.
"""
from __future__ import annotations

import re
import unicodedata
from difflib import SequenceMatcher

from .vocab import HOMOPHONES, SPECIES

# ------------------------------------------------------------------ text helpers
def strip_accents(s: str) -> str:
    s = unicodedata.normalize("NFD", s)
    return "".join(c for c in s if unicodedata.category(c) != "Mn")


def norm(s: str) -> str:
    """Lowercase, no accents, hyphens and apostrophes unified, single spaces."""
    s = strip_accents((s or "").lower()).replace("’", "'").replace("-", " ")
    s = re.sub(r"[^a-z0-9' ]+", " ", s)
    return " ".join(s.split())


def _sing(w: str) -> str:
    if len(w) <= 3 or w.endswith("'s"):
        return w
    if w.endswith("ies") and len(w) > 4:
        return w[:-3] + "y"
    if w.endswith("ces") and len(w) > 6:  # Spanish: alcatraces, perdices, codornices
        return w[:-3] + "z"
    if w.endswith(("ches", "shes", "sses", "xes")):
        return w[:-2]
    if w.endswith("es") and len(w) > 4 and w[-3] in "nrdzl":  # Spanish: leones, jabalies, perdiceras
        return w[:-2] if w[-3] in "nrdzl" and not w.endswith("les") else w[:-1]
    if w.endswith("s") and not w.endswith(("ss", "us", "is")):
        return w[:-1]
    return w


def sing_all(s: str) -> str:
    return " ".join(_sing(w) for w in s.split())


# ------------------------------------------------------------------ numbers
UNITS_EN = {"zero": 0, "one": 1, "two": 2, "three": 3, "four": 4, "five": 5, "six": 6, "seven": 7, "eight": 8,
            "nine": 9, "ten": 10, "eleven": 11, "twelve": 12, "thirteen": 13, "fourteen": 14, "fifteen": 15,
            "sixteen": 16, "seventeen": 17, "eighteen": 18, "nineteen": 19}
TENS_EN = {"twenty": 20, "thirty": 30, "forty": 40, "fourty": 40, "fifty": 50, "sixty": 60, "seventy": 70,
           "eighty": 80, "ninety": 90}
UNITS_ES = {"cero": 0, "un": 1, "uno": 1, "una": 1, "dos": 2, "tres": 3, "cuatro": 4, "cinco": 5, "seis": 6,
            "siete": 7, "ocho": 8, "nueve": 9, "diez": 10, "once": 11, "doce": 12, "trece": 13, "catorce": 14,
            "quince": 15, "dieciseis": 16, "diecisiete": 17, "dieciocho": 18, "diecinueve": 19, "veinte": 20,
            "veintiuno": 21, "veintiun": 21, "veintidos": 22, "veintitres": 23, "veinticuatro": 24, "veinticinco": 25,
            "veintiseis": 26, "veintisiete": 27, "veintiocho": 28, "veintinueve": 29}
TENS_ES = {"treinta": 30, "cuarenta": 40, "cincuenta": 50, "sesenta": 60, "setenta": 70, "ochenta": 80, "noventa": 90}
HUNDREDS_ES = {"cien": 100, "ciento": 100, "doscientos": 200, "doscientas": 200, "trescientos": 300,
               "trescientas": 300, "cuatrocientos": 400, "quinientos": 500}
WORDNUM = {**UNITS_EN, **TENS_EN, **UNITS_ES, **TENS_ES, **HUNDREDS_ES, "hundred": 100, "dozen": 12, "docena": 12}
NUM_WORD_RE = "|".join(sorted(WORDNUM, key=len, reverse=True))


def words_to_digits(text: str) -> str:
    """'forty two griffons' -> '42 griffons'; 'cuarenta y dos' -> '42'; 'a hundred and twenty' -> '120'."""
    toks = re.findall(r"\w+|[^\w\s]|\s+", text)
    out, i = [], 0
    while i < len(toks):
        t = strip_accents(toks[i].lower())
        if t in WORDNUM and not (t in ("un", "una", "uno", "one") and _next_word(toks, i) in ("of", "de", "or", "o", "pair", "pareja", "couple", "par")):
            total, cur, j, used = 0, 0, i, False
            while j < len(toks):
                w = strip_accents(toks[j].lower())
                if toks[j].isspace() or w == "-":
                    j += 1
                    continue
                if w in ("and", "y") and used and _next_word(toks, j) in WORDNUM:
                    j += 1
                    continue
                if w == "a" and _next_word(toks, j) in ("hundred", "dozen"):
                    j += 1
                    continue
                if w not in WORDNUM:
                    break
                v = WORDNUM[w]
                if w in ("hundred",):
                    cur = (cur or 1) * 100
                elif w in ("dozen", "docena"):
                    cur = (cur or 1) * 12
                elif w in HUNDREDS_ES:
                    total += cur
                    cur = v
                else:
                    cur += v
                used = True
                j += 1
            k = j
            while k > i and toks[k - 1].isspace():
                k -= 1
            out.append(str(total + cur))
            out.extend(toks[k:j])
            i = j
        else:
            out.append(toks[i])
            i += 1
    return "".join(out)


def _next_word(toks, i):
    for t in toks[i + 1:]:
        if not t.isspace() and t != "-":
            return strip_accents(t.lower())
    return ""


# ------------------------------------------------------------------ dictionary
class Vocab:
    """Names the free parser can recognise: built-in species plus the operator's own."""

    def __init__(self, extra: list[tuple[str, str, str]] | None = None):
        self.entries: list[dict] = []
        self.by_key: dict[str, dict] = {}
        self.by_nospace: dict[str, dict] = {}
        self.tails: dict[str, list[dict]] = {}
        for en, es, sci, group in SPECIES:
            self._add({"en": en, "es": es, "sci": sci, "group": group})
        for name, sci, group in extra or []:
            hit = self.by_key.get(norm(sci)) if sci else None
            if hit:
                self._key(name, hit)
            elif name:
                self._add({"en": name, "es": name, "sci": sci, "group": group or ""})
        self.homophones = {norm(k): norm(v) for k, v in HOMOPHONES.items()}

    def _add(self, e):
        self.entries.append(e)
        for k in (e["en"], e["es"], e["sci"]):
            self._key(k, e)

    def _key(self, name, e):
        if not name:
            return
        n = norm(name)
        short = " ".join(w for w in n.split() if w not in ("de", "del", "of", "the", "la", "el"))
        keys = {n, sing_all(n), short, sing_all(short)}
        keys |= {k.replace("'", "") for k in keys}  # "bonellis eagle", "corys shearwater"
        for k in keys:
            self.by_key.setdefault(k, e)
            self.by_nospace.setdefault(k.replace(" ", ""), e)
            words = k.split()
            for n in (1, 2):  # "imperial eagle", "spoonbill", "bee eater"
                if len(words) > n:
                    tail = " ".join(words[-n:])
                    if len(tail) >= 4:
                        lst = self.tails.setdefault(tail, [])
                        if e not in lst:
                            lst.append(e)

    def _exact(self, k: str):
        for cand in (k, sing_all(k)):
            if cand in self.by_key:
                return self.by_key[cand]
            if cand.replace(" ", "") in self.by_nospace:
                return self.by_nospace[cand.replace(" ", "")]
        return None

    def match(self, name: str) -> tuple[dict | None, float]:
        """Best entry for a typed/dictated name and a 0..1 confidence (>=0.92 sure, 0.84-0.92 check)."""
        k = sing_all(norm(name))
        if not k:
            return None, 0.0
        # known mis-hearings, also when slightly misspelt
        h = self.homophones.get(k) or self.homophones.get(norm(name))
        if not h:
            for hk, hv in self.homophones.items():
                if abs(len(hk) - len(k)) <= 2 and len(k) >= 5 and SequenceMatcher(None, k, hk).ratio() >= 0.9:
                    h = hv
                    break
        if h:
            k = sing_all(h)
            h2 = self.homophones.get(k) or self.homophones.get(norm(h))
            if h2:
                k = sing_all(h2)
        e = self._exact(k)
        if e:
            return e, 1.0
        best, score = None, 0.0
        for key, e in self.by_key.items():
            if abs(len(key) - len(k)) > max(3, len(k) // 3):
                continue
            r = SequenceMatcher(None, k, key).ratio()
            if r > score:
                best, score = e, r
        # the distinctive end of a name: "spoonbils" -> "eurasian spoonbill"
        for tail, lst in self.tails.items():
            if abs(len(tail) - len(k)) > 3:
                continue
            r = SequenceMatcher(None, k, tail).ratio()
            if r >= 0.86:
                r = (0.95 if r >= 0.97 else 0.9) if len(lst) == 1 else 0.85
                if r > score:
                    best, score = lst[0], r
        return best, score


# ------------------------------------------------------------------ parsing
# Doubt about WHICH species ("some kind of warbler", "sp."): the row is flagged and never guessed.
VAGUE = re.compile(r"\b(unidentified|unknown|sp|spp|kind of|sort of|some kind of|sin identificar|tipo de|especie de|"
                   r"alg[uú]n tipo de)\b", re.I)
# Words about HOW MANY ("lots of", "muchas"): dropped, they don't make the species uncertain.
QUANTITY = re.compile(r"\b(some|several|few|a few|lots of|loads of|lots|loads|heaps|many|plenty of|plenty|"
                      r"algun[oa]s?|vari[oa]s|much[oa]s|much[ií]sim[oa]s|un mont[oó]n de|bastantes|un grupo de|"
                      r"grupo de|a group of|a pod of|pod of|m[aá]s de|more than|over|about|around|approx\w*|"
                      r"aproximadamente|cerca de|casi|almost|unos|unas)\b", re.I)
DOUBT = re.compile(r"(\?|\b(probably|probable|prob|possible|poss|maybe|perhaps|likely|i think|not sure|"
                   r"posible|probablemente|quiz[aá]s?|tal vez|creo que|no seguro)\b)", re.I)
HEARD = re.compile(r"\b(heard( only)?|calling|call(ed|ing)?|singing|o[ií]d[oa]s?|o[ií]mos|escuchad[oa]s?|"
                   r"escuchamos|cantando|oyeron|oy[oó]|o[ií]a|o[ií]an|oyendo|se escuch\w*|escucharon)\b|\(h\)|(^|\s)h(\s|$)",
                   re.I)
NEGATION = re.compile(r"^\s*(no|not|none|without|missed|dipped( on)?|didn'?t see|did not see|no sign of|sin|"
                      r"ning[uú]n[oa]?|no vimos|no hubo|ni|nada de|ni rastro)\b", re.I)
FILLER = re.compile(r"\b(um+|uh+|erm|eh+|like|okay|ok|so|then|also|plus|we saw|we had|we spotted|saw|seen|got|"
                    r"and then|bueno|pues|vale|este|vimos|hemos visto|visto|vistos|vista|vistas|tambi[eé]n|"
                    r"solo|s[oó]lo|only|just|enorme|enormes|grande|grandes|era|eran|fue|fueron|was|were|se|briefly|brevemente|too|"
                    r"de noche|por la noche|noche|ma[nñ]ana|tarde|at night|night|morning|afternoon|evening|today|hoy|"
                    r"peque[nñ]o|peque[nñ]a|precios[oa]s?|incre[ií]ble|espectacular|"
                    r"preciosa|bonit[oa]s?|huge|big|small|little|beautiful|amazing|gorgeous|stunning|lovely|"
                    r"hab[ií]a|hubo|luego|despu[eé]s|the|a|an|un|una|el|la|los|las|of|de|del)\b", re.I)
SPOKEN_PUNCT = re.compile(r"\b(comma|coma|full stop|period|punto( y coma)?|next|siguiente|new line|nueva l[ií]nea)\b", re.I)
CORRECTION = re.compile(r"\b(no wait|wait no|sorry|i mean|actually|correction|perd[oó]n|digo|mejor dicho|no espera)\b|"
                        r"(?<=\d)\s*,?\s*no\s*,?\s*(?=\d)", re.I)
SPLIT = re.compile(r"[\n;,•·]+|\s+\b(?:and|y|e)\b\s+", re.I)
PAIR = re.compile(r"\b(a |one |una |un )?(pair|pareja|couple|par)( of| de)?\b", re.I)
TIMES = re.compile(r"\b(times|por|x)\s+(?=\d)", re.I)


def _prepare(text: str) -> str:
    s = unicodedata.normalize("NFKC", text or "")
    s = SPOKEN_PUNCT.sub(",", s)
    s = words_to_digits(s)
    s = re.sub(r"\b(?:entre|between)\s+(\d{1,5})\s+(?:y|and)\s+(\d{1,5})\b", r"\1-\2", s, flags=re.I)
    s = re.sub(r"\b(\d{1,5})\s*(?:or|o|to|a|-|–)\s*(\d{1,5})\b",
               lambda m: m.group(2) if int(m.group(2)) >= int(m.group(1)) else m.group(0), s, flags=re.I)
    s = re.sub(r"(\d{1,5})\s*,?\s*(?:no|not|sorry|i mean|perd[oó]n|digo|mejor dicho)\s*,?\s*(\d{1,5})", r"\2", s, flags=re.I)
    s = re.sub(r"\b(a|an|unos?|unas?)\s+(?=\d)", "", s, flags=re.I)
    s = TIMES.sub("x", s)
    return s


def _split_runs(chunk: str) -> list[str]:
    """'40 griffons 2 black vultures lynx x1' -> ['40 griffons', '2 black vultures lynx x1'] etc.
    Starts a new entry at a number that follows words, unless it's an 'x2' count."""
    toks = chunk.split()
    plain = [t.strip("!?") for t in toks if t.strip("!?")]
    if plain and re.fullmatch(r"\d{1,5}", plain[-1]) and not re.fullmatch(r"\d{1,5}\+?", plain[0]):
        # "griffon vulture 40 black vulture 6 imperial eagle 2!": the count comes after each name
        parts, cur = [], []
        for t in toks:
            cur.append(t)
            if re.fullmatch(r"\d{1,5}[!?]*", t):
                parts.append(" ".join(cur))
                cur = []
        if cur:
            parts[-1:] = [parts[-1] + " " + " ".join(cur)] if parts else [" ".join(cur)]
        return parts
    parts, cur, has_word = [], [], False
    for t in toks:
        if re.fullmatch(r"\d{1,5}\+?", t) and has_word and cur and not re.fullmatch(r"[x×]", cur[-1], re.I):
            parts.append(" ".join(cur))
            cur, has_word = [], False
        cur.append(t)
        if re.search(r"[^\W\d_]{2,}", t):
            has_word = True
    if cur:
        parts.append(" ".join(cur))
    return parts


def parse_entry(text: str, vocab: Vocab | None = None) -> dict | None:
    src = " ".join((text or "").split()).strip(" .")
    if not src or NEGATION.search(src):
        return None
    s = src
    # quick self-corrections: "3 no 4 griffons", "griffons 3 sorry 4" -> keep the later number
    if CORRECTION.search(s):
        nums = re.findall(r"\d{1,5}", s)
        s = CORRECTION.sub(" ", s)
        if len(nums) >= 2:
            s = re.sub(r"\d{1,5}", "", s, count=len(nums) - 1)
    star = "!" in s
    s = s.replace("!", " ")
    sure = not DOUBT.search(s)
    heard = bool(HEARD.search(s))
    vague = bool(VAGUE.search(s))
    count: int | None = None
    if PAIR.search(s) and not re.search(r"\d", s):
        count = 2
        s = PAIR.sub(" ", s)
    m = re.search(r"(?:[x×]\s*(\d{1,5})\b|\((\d{1,5})\)|\b(\d{1,5})\s*[x×]\b)", s, re.I)
    if m:
        count = int(next(g for g in m.groups() if g))
        s = s[:m.start()] + " " + s[m.end():]
    else:
        m = re.search(r"\b(\d{1,5})\+?\b", s)
        if m:
            count = int(m.group(1))
            s = s[:m.start()] + " " + s[m.end():]
    s = DOUBT.sub(" ", s)
    s = HEARD.sub(" ", s)
    s = VAGUE.sub(" ", s)
    s = QUANTITY.sub(" ", s)
    s = FILLER.sub(" ", s)
    s = re.sub(r"[^\w\s'’-]", " ", s)
    s = " ".join(s.split()).strip(" -'")
    if not s or s.isdigit() or len(s) < 2:
        return None
    row = {"name": "", "sci": "", "count": count, "heard": heard and not count, "sure": sure, "star": star,
           "group": "", "source": src[:200]}
    if norm(s) in GENERIC or sing_all(norm(s)) in GENERIC:
        vague = True
    entry, score = (vocab or default_vocab()).match(s)
    if entry and score >= 0.84 and not vague:
        row.update(name=entry["en"], sci=entry["sci"], group=entry["group"], _entry=entry)
        if score < 0.92:  # corrected a fair bit: ask the guide to glance at it
            row["sure"] = False
    else:
        row["name"] = sing_all(s.lower()).capitalize() if s == s.lower() else s
        row["sure"] = False
        if vague:
            t = sing_all(s.lower()) if s == s.lower() else s
            row["name"] = t[:1].upper() + t[1:]
        elif entry and score >= 0.7:  # a likely match: suggest it, flagged
            row.update(name=entry["en"], sci=entry["sci"], group=entry["group"], _entry=entry)
    row["name"] = row["name"][:120]
    return row


GENERIC = {norm(w) for w in (
    "bird birds raptor raptors eagle eagles vulture vultures warbler warblers duck ducks gull gulls hawk hawks owl owls "
    "falcon falcons heron herons egret egrets wader waders dolphin dolphins whale whales deer snake snakes lizard "
    "lizards frog frogs bat bats butterfly butterflies dragonfly dragonflies tit tits finch finches lark larks "
    "ave aves rapaz rapaces aguila aguilas buitre buitres curruca currucas pato patos gaviota gaviotas buho buhos "
    "halcon halcones garza garzas delfin delfines ballena ballenas ciervo serpiente lagartija rana murcielago "
    "mariposa libelula beaked whale beaked whales zifio zifios rorcual rorcuales tortuga tortugas turtle turtles "
    "shearwater shearwaters pardela pardelas tern terns charran charranes shark sharks tiburon tiburones ray rays "
    "manta mantas petrel petrels paino rorqual rorquals").split()}

ATTR = re.compile(r"^(\d{1,5}\+?|x\d{1,5}|x|×|\(\d{1,5}\)|pair|pareja|couple|heard|o[ií]d[oa]s?|calling|"
                  r"singing|cantando|escuchad[oa]s?|h|\?|!+)$", re.I)


def _segment(part: str, vocab: Vocab) -> list[str]:
    """Split 'blak vultures imperial eagle pair links x1 heard eagle owl' into one entry per species
    using the dictionary. Numbers and flags go with the species they belong to."""
    toks = re.findall(r"\d{1,5}\+?|x\d{1,5}|\(\d{1,5}\)|[\w'’-]+|[?!]+", part, re.I)
    noise = {"kind", "sort", "type", "tipo", "especie", "sp", "spp", "possibly", "maybe"}
    words = [(i, t) for i, t in enumerate(toks) if not ATTR.match(t) and not FILLER.fullmatch(t)
             and t.lower() not in noise
             and not VAGUE.fullmatch(t) and not QUANTITY.fullmatch(t) and not DOUBT.fullmatch(t)]
    if len(words) < 3:
        return [part]
    whole, score = vocab.match(" ".join(t for _, t in words))
    if whole and score >= 0.92:
        return [part]
    n = len(words)
    best = [(0.0, [])] + [(-1.0, [])] * n  # best[j]: (score, cut points) for words[:j]
    for j in range(1, n + 1):
        for L in range(1, min(4, j) + 1):
            prev_score, cuts = best[j - L]
            if prev_score < 0:
                continue
            name = " ".join(t for _, t in words[j - L:j])
            e, sc = vocab.match(name)
            gain = (sc if e and sc >= 0.84 else -0.6) * L
            if prev_score + gain > best[j][0]:
                best[j] = (prev_score + gain, cuts + [j - L])
    total, cuts = best[n]
    if total <= 0 or len(cuts) < 2:
        return [part]
    # turn word cuts into token ranges; a leading count/"pair"/"heard" belongs to the next species,
    # a trailing "x1", "?" or "!" to the previous one
    starts = [words[c][0] for c in cuts]
    word_idx = {i for i, _ in words}
    trailing = re.compile(r"x\d{1,5}|\(\d{1,5}\)|[?!]+|x|×|pair|pareja|couple", re.I)
    pieces = []
    for si, start in enumerate(starts):
        lo = start
        # walk back over leading words that belong to this species: counts, "heard", "some", "maybe"...
        while lo > 0 and (si == 0 or lo > starts[si - 1] + 1) and lo - 1 not in word_idx:
            t = toks[lo - 1]
            nxt = toks[lo].lower() if lo < len(toks) else ""
            if trailing.fullmatch(t) and not (t.lower() in ("pair", "pareja", "couple") and nxt in ("of", "de")):
                break
            lo -= 1
        if si == 0:
            lo = 0
        pieces.append(lo)
    pieces.append(len(toks))
    return [" ".join(toks[pieces[i]:pieces[i + 1]]) for i in range(len(pieces) - 1)]


def parse_tally(text: str, vocab: Vocab | None = None, lang: str = "en") -> list[dict]:
    """Split free text into species rows. Duplicates are merged keeping the highest count."""
    vocab = vocab or default_vocab()
    out: dict[str, dict] = {}
    replace_last, last_key = False, None
    for chunk in SPLIT.split(_prepare(text)):
        if not chunk or chunk.lower() in ("and", "y", "e"):
            continue
        doubt = False
        if CORRECTION.fullmatch(chunk.strip(" .")) or re.fullmatch(r"\s*(no|perd[oó]n|sorry)[\s,.]*", chunk, re.I):
            replace_last = True  # "perdón" on its own: the next species replaces the previous one
            continue
        for part in [p for run in _split_runs(chunk) for p in _segment(run, vocab)]:
            if DOUBT.search(part) and not re.sub(DOUBT, " ", FILLER.sub(" ", part)).strip(" ,.?"):
                doubt = True  # "creo que", "maybe" on their own: about the next species
                continue
            if replace_last and re.fullmatch(r"\s*\d{1,5}\s*", part):
                if last_key in out:  # "doce, perdón, catorce": a corrected count
                    out[last_key]["count"] = int(part)
                replace_last = False
                continue
            row = parse_entry(part, vocab)
            if not row:
                continue
            if doubt:
                row["sure"], doubt = False, False
            if replace_last and last_key in out:
                del out[last_key]
            replace_last = False
            e = row.pop("_entry", None)
            if e and lang == "es":
                row["name"] = e["es"]
            key = (row["sci"] or row["name"]).lower()
            if key in out:
                prev = out[key]
                if row["count"] and (not prev["count"] or row["count"] > prev["count"]):
                    prev["count"] = row["count"]
                prev["star"] = prev["star"] or row["star"]
                prev["sure"] = prev["sure"] and row["sure"]
            else:
                out[key] = row
            last_key = key
    return list(out.values())


_default = None


def default_vocab() -> Vocab:
    global _default
    if _default is None:
        _default = Vocab()
    return _default


# ------------------------------------------------------------------ checking AI output
STOP = {"the", "a", "an", "and", "on", "at", "in", "of", "over", "near", "by", "with", "we", "saw", "seen", "heard",
        "el", "la", "los", "las", "de", "del", "en", "con", "y", "un", "una", "unos", "unas", "sobre", "por"}


def supported_by(source: str, text: str) -> bool:
    """True if the words the model quoted really appear in what the guide wrote (allowing typos)."""
    src = norm(_prepare(source))
    hay = norm(_prepare(text))
    if not src:
        return False
    if src in hay:
        return True
    words = [w for w in src.split() if not w.isdigit() and w not in STOP and len(w) > 1]
    if not words:
        return False
    hay_words = hay.split()
    hits = sum(1 for w in words
               if w in hay_words or any(SequenceMatcher(None, w, h).ratio() >= 0.8 for h in hay_words))
    return hits / len(words) >= 0.8


def clean_ai_rows(rows, raw_text: str = "") -> list[dict]:
    """Validate the model's JSON. Rows whose quoted source isn't in the guide's text are dropped."""
    if isinstance(rows, dict):
        rows = rows.get("species") or rows.get("rows") or []
    out = []
    if not isinstance(rows, list):
        return out
    for o in rows[:300]:
        if not isinstance(o, dict) or not str(o.get("name", "")).strip():
            continue
        source = str(o.get("source", "") or "").strip()
        if raw_text and not supported_by(source or str(o.get("name", "")), raw_text):
            continue  # the model added something the guide never said
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
            "source": source[:200],
        })
    return out
