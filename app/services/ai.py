"""Optional AI drafting and reading. Used when an API key is set:
- LLM_API_KEY: any OpenAI-compatible provider. The default is Groq, which has a free tier.
- ANTHROPIC_API_KEY: Claude, if you later want the strongest writing.

Every prompt carries the same hard rule: use only the guide's notes and species list, never
invent sightings. Species rows must quote the guide's own words, and the app checks that.
The guide still approves every day before guests see it.
"""
from __future__ import annotations

import json
import logging
import re
import time

import httpx

from ..config import settings

log = logging.getLogger("tripreports.ai")

LANG_NAMES = {"en": "English", "es": "Spanish", "de": "German", "fr": "French"}
TONES = {
    "warm": "warm and personal, like a friendly guide writing to guests they enjoyed spending time with; plain words, no purple prose",
    "expert": "knowledgeable and precise, like an experienced naturalist; calm, factual, with small ecological details only where the notes support them",
    "lively": "upbeat and lively with light humour, but never silly or exaggerated",
}
SYSTEM = ("You help wildlife and birding tour guides write trip reports for their guests. "
          "Guides type fast or dictate into a phone in the field, so their notes contain spelling mistakes, "
          "speech-recognition errors, missing punctuation, mixed English and Spanish, and quick corrections. "
          "You understand what they meant and write it correctly. You only ever use facts the guide gave you. "
          "You never invent animals, sightings, numbers, times, places, people or weather.")


class AIError(Exception):
    def __init__(self, code: str):
        super().__init__(code)
        self.code = code  # unavailable | rate_limited | refused | bad_output | too_long


_client = None


def _anthropic(prompt: str, fast: bool, max_tokens: int) -> tuple[str, int, int]:
    global _client
    try:
        import anthropic
    except ImportError as e:
        raise AIError("unavailable") from e
    if _client is None:
        _client = anthropic.Anthropic(api_key=settings.anthropic_api_key, max_retries=2, timeout=60)
    try:
        resp = _client.messages.create(
            model=settings.anthropic_fast_model if fast else settings.anthropic_model,
            max_tokens=max_tokens, system=SYSTEM, messages=[{"role": "user", "content": prompt}])
    except anthropic.RateLimitError as e:
        raise AIError("rate_limited") from e
    except anthropic.BadRequestError as e:
        log.warning("Claude bad request: %s", e)
        raise AIError("too_long") from e
    except anthropic.APIError as e:
        log.warning("Claude API error: %s", e)
        raise AIError("unavailable") from e
    if getattr(resp, "stop_reason", None) == "refusal":
        raise AIError("refused")
    text = "".join(getattr(b, "text", "") for b in resp.content).strip()
    u = getattr(resp, "usage", None)
    return text, getattr(u, "input_tokens", 0) or 0, getattr(u, "output_tokens", 0) or 0


# Free providers retire models often (Groq dropped Llama 3.3 70B from its free tier in August 2026).
# So the app tries a chain of models: the configured ones first, then current Groq models, skipping any
# known to be retired or that answered "model not found" since the server started.
GROQ_CHAIN = ["openai/gpt-oss-120b", "openai/gpt-oss-20b", "qwen/qwen3.8-27b"]
RETIRED = {"llama-3.3-70b-versatile", "llama-3.1-8b-instant", "qwen/qwen3-32b", "qwen/qwen3.6-27b",
           "meta-llama/llama-4-scout-17b-16e-instruct", "meta-llama/llama-4-maverick-17b-128e-instruct",
           "moonshotai/kimi-k2-instruct", "moonshotai/kimi-k2-instruct-0905", "gemma2-9b-it",
           "llama3-70b-8192", "llama3-8b-8192", "mixtral-8x7b-32768"}
_gone: set[str] = set()
THINK = re.compile(r"<think>.*?</think>", re.S | re.I)


def model_chain() -> list[str]:
    configured = [m.strip() for m in (settings.llm_model or "").split(",") if m.strip()]
    extra = GROQ_CHAIN if "groq.com" in settings.llm_base_url else []
    chain = []
    for m in configured + extra:
        if m not in chain and m not in RETIRED and m not in _gone:
            chain.append(m)
    return chain


class _Next(Exception):
    """This model can't answer right now; try the next one."""

    def __init__(self, reason: str):
        super().__init__(reason)
        self.reason = reason


def _call_model(model: str, prompt: str, max_tokens: int, json_mode: bool, effort: str = "low") -> tuple[str, int, int]:
    reasoning = "gpt-oss" in model or "qwen3" in model
    body = {"model": model, "temperature": 0.2 if not json_mode else 0,
            # reasoning models spend part of the budget thinking before they answer
            "max_tokens": max_tokens + ((1500 if effort == "medium" else 800) if reasoning else 0),
            "messages": [{"role": "system", "content": SYSTEM}, {"role": "user", "content": prompt}]}
    if json_mode:
        body["response_format"] = {"type": "json_object"}
    if "gpt-oss" in model:
        body.update(reasoning_effort=effort, include_reasoning=False)
    headers = {"Authorization": f"Bearer {settings.llm_api_key}"}
    url = f"{settings.llm_base_url}/chat/completions"
    for attempt in range(3):
        try:
            r = httpx.post(url, json=body, timeout=45, headers=headers)
        except httpx.HTTPError as e:
            log.warning("AI request to %s failed: %s", model, e)
            raise _Next("network") from e
        low = r.text[:600].lower()
        if r.status_code == 429:
            wait = _retry_after(r)
            if attempt == 0 and wait <= 8:
                time.sleep(wait)
                continue
            raise _Next("rate_limited")
        if r.status_code in (400, 404, 422) and ("model" in low and any(
                w in low for w in ("not found", "decommission", "does not exist", "not exist", "deprecat", "no access"))):
            log.warning("AI model %s is not available (%s); skipping it from now on", model, r.text[:200])
            _gone.add(model)
            raise _Next("model_gone")
        if r.status_code == 400 and "response_format" in body and ("response_format" in low or "json" in low):
            body.pop("response_format")  # provider or model without JSON mode
            continue
        if r.status_code == 400 and ("reasoning_effort" in low or "include_reasoning" in low):
            body.pop("reasoning_effort", None)
            body.pop("include_reasoning", None)
            continue
        if r.status_code in (401, 403):
            log.error("The AI key was rejected (%s): %s", r.status_code, r.text[:200])
            raise AIError("unavailable")
        if r.status_code == 413 or (r.status_code == 400 and ("too long" in low or "context" in low or "tokens" in low)):
            log.warning("AI request too long for %s: %s", model, r.text[:200])
            raise _Next("too_long")
        if r.status_code >= 300:
            log.warning("AI error from %s %s: %s", model, r.status_code, r.text[:300])
            raise _Next("error")
        try:
            d = r.json()
            text = THINK.sub("", d["choices"][0]["message"].get("content") or "").strip()
            u = d.get("usage") or {}
        except (ValueError, KeyError, IndexError) as e:
            raise _Next("bad_output") from e
        if not text:
            raise _Next("bad_output")  # e.g. the model used its whole budget thinking
        return text, int(u.get("prompt_tokens") or 0), int(u.get("completion_tokens") or 0)
    raise _Next("error")


def _retry_after(r: httpx.Response) -> float:
    try:
        return float(r.headers.get("retry-after", "30"))
    except ValueError:
        return 30.0


def _openai_compatible(prompt: str, max_tokens: int, json_mode: bool, effort: str = "low") -> tuple[str, int, int]:
    reasons = []
    for model in model_chain():
        try:
            return _call_model(model, prompt, max_tokens, json_mode, effort)
        except _Next as e:
            reasons.append(e.reason)
    log.warning("No AI model could answer: %s", reasons or "no models configured")
    if reasons and all(r == "rate_limited" for r in reasons):
        raise AIError("rate_limited")
    if reasons and all(r == "too_long" for r in reasons):
        raise AIError("too_long")
    raise AIError("unavailable")


def check() -> list[dict]:
    """Ask each model in the chain for a tiny answer. For the admin page."""
    out = []
    if settings.ai_provider == "anthropic":
        try:
            _anthropic('Reply with only the word "ok".', True, 20)
            return [{"model": settings.anthropic_fast_model, "ok": True, "detail": ""}]
        except AIError as e:
            return [{"model": settings.anthropic_fast_model, "ok": False, "detail": e.code}]
    if not settings.llm_api_key:
        return []
    for model in model_chain():
        try:
            text, _, _ = _call_model(model, 'Reply with only the JSON {"ok": true}.', 50, True)
            out.append({"model": model, "ok": True, "detail": text[:60]})
        except _Next as e:
            out.append({"model": model, "ok": False, "detail": e.reason})
        except AIError as e:
            out.append({"model": model, "ok": False, "detail": "key_rejected" if e.code == "unavailable" else e.code})
            break
    return out


def complete(prompt: str, *, fast: bool = False, max_tokens: int = 1200, json_mode: bool = False,
             effort: str = "low") -> tuple[str, int, int]:
    """Returns (text, input_tokens, output_tokens). Raises AIError."""
    if settings.ai_provider == "anthropic":
        text, i, o = _anthropic(prompt, fast, max_tokens)
    elif settings.ai_provider == "openai":
        text, i, o = _openai_compatible(prompt, max_tokens, json_mode, effort)
    else:
        raise AIError("unavailable")
    if not text:
        raise AIError("bad_output")
    return text, i, o


def _json(text: str):
    m = re.search(r"(\[.*\]|\{.*\})", text, re.S)
    if not m:
        raise AIError("bad_output")
    try:
        return json.loads(m.group(1))
    except json.JSONDecodeError as e:
        raise AIError("bad_output") from e


def species_prompt(tally: str, notes: str, lang: str, context: str, known: str = "") -> str:
    ln = LANG_NAMES.get(lang, "English")
    return f"""Read a wildlife guide's field records and list every animal species they recorded.
{context}
The guide may have typed fast or dictated into a phone. Expect spelling mistakes ("grifon", "kingfischer"),
speech-recognition errors ("links" for lynx, "wales" for whales, "who poe" for hoopoe), number words
("forty two", "cuarenta y dos"), counts before or after the name ("x3", "times three", "por tres", "3 griffons",
"griffons 3"), "pair"/"pareja" = 2, no punctuation between species, mixed English and Spanish, and quick
corrections ("three no four griffons" means 4).

Rules:
1. Include only animals the guide says were SEEN or HEARD today. Leave out animals they say they did NOT see
   ("no lynx today", "we missed the bustards", "no vimos la nutria"), only hoped for, or talk about in general.
2. Use the TALLY first. Also add species that appear only in the NOTES, if the notes say they were seen or heard.
3. Write each "name" as the correct standard common name in {ln} for this region, correctly spelled,
   and give its scientific name in "sci".
4. "source": copy the guide's own words for this species EXACTLY as written, including their typos
   (e.g. "fourty grifon vultures"). Never write a source that is not in the text.
5. If a name is vague ("eagle", "some warblers", "a raptor") or you are not confident which species it is,
   keep the guide's wording as "name", set "sci" to "" and "sure" to false. Never guess a species.
6. If the guide shows doubt ("?", "probably", "possible", "creo que"), set "sure" to false but still give the
   best name. If you corrected a name that could reasonably be two different species, set "sure" to false.
   Quantity words are NOT doubt: "some", "several", "lots of", "unos", "varios", "muchas" just mean the count
   is unknown or approximate ("unos veinte" = about 20, so count 20 and sure true).
7. "count": the number (after any correction), or null. "heard": true only if heard and not seen.
   "star": true if marked "!" or called a highlight. "group": birds, mammals, reptiles, amphibians, fish,
   insects, arachnids or other.
Examples of messy input and what it means:
- "unos veinte calderones tropicales delfines mulares por ocho" -> Short-finned Pilot Whale / Calderón tropical 20,
  Common Bottlenose Dolphin / Delfín mular 8.
- "vimos un cacha lote y luego tortuga voba!" -> Sperm Whale / Cachalote (1), Loggerhead / Tortuga boba (star).
- "40 grifons, links x1, heard eagle owl, no otters today" -> Griffon Vulture 40, Iberian Lynx 1,
  Eurasian Eagle-Owl heard; no otter row.
- "tres no cuatro abubillas y un par de abejarucos" -> Hoopoe / Abubilla 4, European Bee-eater / Abejaruco 2.
- "posible zifio?" -> Cuvier's Beaked Whale only if the region makes it the obvious one, otherwise keep "Zifio"
  with sci "" ; sure false either way.
{("Species this operator has recorded before (prefer these spellings when they match): " + known) if known else ""}

Reply with only a JSON object:
{{"species": [{{"name": "Griffon Vulture", "sci": "Gyps fulvus", "count": 40, "heard": false, "sure": true,
"star": false, "group": "birds", "source": "fourty grifon vultures"}}]}}

TALLY:
\"\"\"
{tally[:6000] or "(empty)"}
\"\"\"

NOTES:
\"\"\"
{notes[:8000] or "(empty)"}
\"\"\""""


def parse_species(tally: str, notes: str, lang: str, context: str, known: str = "") -> tuple[object, int, int]:
    text, i, o = complete(species_prompt(tally, notes, lang, context, known), max_tokens=2500, json_mode=True)
    return _json(text), i, o


def _fix_block(previous: str, problems: str) -> str:
    if not problems:
        return ""
    return f"""

A first draft had mistakes. Write a new version that fixes ALL of these, keeping everything that was right:
{problems}

First draft:
\"\"\"
{previous[:4000]}
\"\"\"
"""


WRITING_RULES = """What you may do:
- Combine and reorder the notes into fluent, well-built sentences, grouped in a sensible order
  (how the outing went, the main sightings, anything else worth remembering).
- Write flowing prose that is pleasant to read, not a list: don't cram every species into one sentence. Open with the
  best sighting (marked [highlight], or what the notes make most of) and give it a sentence of its own with every
  detail the notes give; group the rest naturally.
- Use the counts from the species list. If the notes and the list disagree (a correction like "3 no 4"), the list is right.
- Add a few short warm phrases that state no fact ("a great outing", "thank you for sharing it with us").
- Say where things happened only if the notes say so. Never assume sea, shore, cliffs, forest or sky.

What you must NOT add, unless the notes say it:
- weather, sky, light, sun, wind, sea state or colours;
- sounds, calls, songs, smells;
- behaviour (jumping, playing, feeding, resting, approaching the boat...), appearance, colours or sizes of animals;
- places (beach, cliffs, forest, harbour...), times, distances, ages (calves, juveniles), numbers;
- what guests felt or did;
- any species not on the list, and facts about a species from your own knowledge.
Every sentence must be traceable to the notes or the species list. When in doubt, leave it out.
A species marked [UNCONFIRMED] is "possible" or "probable", never certain. A species marked [heard only] was heard, not seen;
never say any other species was heard.
Don't mention the day number ("Day 1", "first day"), and don't say "morning" or "afternoon" unless the notes do.
Plain text only: no headings, lists, bold, markdown, emoji or scientific names. Don't repeat the species checklist:
the report already ends with one, so mention only the sightings that matter."""


def day_prompt(n: int, date_s: str, place: str, notes: str, species_lines: str, lang: str, tone: str, context: str,
               previous: str = "", problems: str = "") -> str:
    ln = LANG_NAMES.get(lang, 'English')
    return f"""Write the Day {n} section of a wildlife trip report that a tour operator sends to its guests.

Language: every sentence in {ln}, with {ln} common names; translate the notes if they are in another language
and never mix languages.
Style: {TONES.get(tone, TONES['warm'])}. First person plural ("we").
Length: as long as the notes justify, from 2 sentences for thin notes up to about 180 words. Never pad.
It is a summary for guests, not a transcript: don't copy the guide's sentences. Leave out notes meant for the team
(fuel, bookings, reminders, complaints). The notes may contain spelling and dictation mistakes: understand what the
guide meant, but never change a fact, number or time.

{WRITING_RULES}

{context}
Day {n}{', ' + date_s if date_s else ''}{', ' + place if place else ''}

Guide's notes:
\"\"\"
{notes[:8000] or '(none)'}
\"\"\"

Species list for this day:
{species_lines or '(no species listed)'}{_fix_block(previous, problems)}"""


def draft_day(**kw) -> tuple[str, int, int]:
    return complete(day_prompt(**kw), max_tokens=700, effort="medium")


def claims_prompt(text: str, notes: str, species_lines: str) -> str:
    return f"""You are a strict fact-checker for a wildlife trip report. Compare the REPORT with the guide's NOTES and SPECIES LIST.

List every FACTUAL claim in the report that the notes and species list do not support: weather, light, sea state,
sounds or calls, animal behaviour, appearance or colours, places, times, numbers, ages (calves...), what specific
people did, species facts from general knowledge, species not on the list, and anything stated as certain that the
notes call possible.

Do NOT list (these are fine): warm or polite phrases ("a great outing", "we were delighted", "thank you for joining
us"), plain verbs like "we saw", "we spotted" or "we enjoyed", calling a [highlight] species a highlight, the day
number or "first day", and general words like "outing", "trip" or "day".
Translations and rewording of what the notes say are fine. The SPECIES LIST gives the correct names and counts of
what the guide wrote (for example "black vultures" in the notes is the Cinereous Vulture on the list, and "3 no 4"
means 4), so those names and counts are supported. Places (sea, shore, cliffs, water, forest) count as details.

"quote" must be copied EXACTLY from the report (a short phrase, not a whole paragraph).
Reply with only JSON: {{"unsupported": [{{"quote": "...", "why": "..."}}]}}  (an empty list if everything is supported)

NOTES:
\"\"\"
{notes[:8000] or "(none)"}
\"\"\"

SPECIES LIST:
{species_lines or "(none)"}

REPORT:
\"\"\"
{text[:6000]}
\"\"\""""


def unsupported_claims(text: str, notes: str, species_lines: str) -> tuple[list[dict], int, int]:
    """Details in a draft that the notes don't support, as quoted by a second, checking model call.
    Quotes that aren't really in the draft are ignored, so the checker can't invent problems either."""
    out, i, o = complete(claims_prompt(text, notes, species_lines), max_tokens=700, json_mode=True, effort="medium")
    d = _json(out)
    items = d.get("unsupported", []) if isinstance(d, dict) else d if isinstance(d, list) else []
    clean, low = [], " ".join(text.lower().split())
    for it in items[:20]:
        q = str(it.get("quote", "") if isinstance(it, dict) else it).strip().strip('"“”«»')
        if len(q) >= 4 and " ".join(q.lower().split()) in low:
            clean.append({"quote": q[:200], "why": str(it.get("why", "") if isinstance(it, dict) else "")[:200]})
    return clean, i, o


def intro_prompt(days_text: str, n_days: int, n_species: int, guests, lang: str, tone: str, context: str,
                 previous: str = "", problems: str = "") -> str:
    return f"""Write the opening and closing paragraphs of a wildlife trip report a tour operator sends to its guests.

Style: {TONES.get(tone, TONES['warm'])}. Language: every sentence in {LANG_NAMES.get(lang, 'English')}, translating if
the day reports are in another language; never mix languages. First person plural ("we"). Plain text, no emoji, no markdown.
- "intro": 30 to 90 words. Welcome the reader back to the trip: where it was and how many days. Don't list species.
- "summary": 40 to 100 words. Look back on the highlights, mention that {n_species} species were recorded, and thank the guests. No sign-off or names.
Use only facts from the day reports below. Species the day reports call possible or probable must stay that way.

{WRITING_RULES}

{context}
Guests: {guests or '(not given)'}
Days: {n_days}

Day reports:
\"\"\"
{days_text[:20000]}
\"\"\"

Reply with only JSON: {{"intro":"...","summary":"..."}}{_fix_block(previous, problems)}"""


def draft_intro(**kw) -> tuple[dict, int, int]:
    text, i, o = complete(intro_prompt(**kw), max_tokens=700, json_mode=True, effort="medium")
    d = _json(text)
    if not isinstance(d, dict) or not isinstance(d.get("intro"), str):
        raise AIError("bad_output")
    return d, i, o


def season_prompt(facts: dict, lang: str, tone: str) -> str:
    return f"""Write a short season summary (90 to 140 words) that a wildlife tour operator can put on its website or in a newsletter.
Language: {LANG_NAMES.get(lang, 'English')} only. First person plural ("we"). Plain text, 1 or 2 paragraphs, no heading, no emoji, no markdown.
Style: {TONES.get(tone, TONES['warm'])}.
Use only the facts below. Quote percentages exactly as given. Never promise sightings: these are past results, not guarantees. Don't invent places, dates or anecdotes.

Facts (JSON):
{json.dumps(facts, ensure_ascii=False)}"""


def draft_season(facts: dict, lang: str, tone: str) -> tuple[str, int, int]:
    return complete(season_prompt(facts, lang, tone), max_tokens=700)


def proofread_prompt(text: str, lang: str) -> str:
    return f"""Correct the spelling, grammar, punctuation and dictation errors in this text from a wildlife trip report.
Language: {LANG_NAMES.get(lang, "English")}. Fix misspelt species names and capitalise them the way this language
normally does. Keep the guide's words, tone, facts, numbers and times exactly; do not add, remove or reorder
information, and do not make it longer. Keep the paragraph breaks.
Reply with only the corrected text, nothing else.

Text:
\"\"\"
{text[:12000]}
\"\"\""""


def proofread(text: str, lang: str) -> tuple[str, int, int]:
    out, i, o = complete(proofread_prompt(text, lang), max_tokens=2500)
    out = out.strip().strip('"').strip()
    # a proofread that changes length a lot is not a proofread: refuse it
    if not out or not (0.6 * len(text) <= len(out) <= 1.4 * len(text) + 40):
        raise AIError("bad_output")
    return out, i, o
