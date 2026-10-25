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

import httpx

from ..config import settings

log = logging.getLogger("tripreports.ai")

LANG_NAMES = {"en": "English", "es": "Spanish", "de": "German", "fr": "French"}
TONES = {
    "warm": "warm, personal and vivid, like a friendly guide writing to guests they enjoyed spending time with",
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


def _openai_compatible(prompt: str, max_tokens: int, json_mode: bool) -> tuple[str, int, int]:
    body = {"model": settings.llm_model, "temperature": 0.2 if not json_mode else 0,
            "max_tokens": max_tokens,
            "messages": [{"role": "system", "content": SYSTEM}, {"role": "user", "content": prompt}]}
    if json_mode:
        body["response_format"] = {"type": "json_object"}
    try:
        r = httpx.post(f"{settings.llm_base_url}/chat/completions", json=body, timeout=60,
                       headers={"Authorization": f"Bearer {settings.llm_api_key}"})
    except httpx.HTTPError as e:
        log.warning("AI request failed: %s", e)
        raise AIError("unavailable") from e
    if r.status_code == 429:
        raise AIError("rate_limited")
    if r.status_code in (400, 413) and json_mode and "response_format" in r.text:
        return _openai_compatible(prompt, max_tokens, False)  # provider without JSON mode
    if r.status_code in (400, 413):
        log.warning("AI bad request %s: %s", r.status_code, r.text[:300])
        raise AIError("too_long")
    if r.status_code >= 300:
        log.warning("AI error %s: %s", r.status_code, r.text[:300])
        raise AIError("unavailable")
    try:
        d = r.json()
        text = (d["choices"][0]["message"].get("content") or "").strip()
        u = d.get("usage") or {}
    except (ValueError, KeyError, IndexError) as e:
        raise AIError("bad_output") from e
    return text, int(u.get("prompt_tokens") or 0), int(u.get("completion_tokens") or 0)


def complete(prompt: str, *, fast: bool = False, max_tokens: int = 1200, json_mode: bool = False) -> tuple[str, int, int]:
    """Returns (text, input_tokens, output_tokens). Raises AIError."""
    if settings.ai_provider == "anthropic":
        text, i, o = _anthropic(prompt, fast, max_tokens)
    elif settings.ai_provider == "openai":
        text, i, o = _openai_compatible(prompt, max_tokens, json_mode)
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
7. "count": the number (after any correction), or null. "heard": true only if heard and not seen.
   "star": true if marked "!" or called a highlight. "group": birds, mammals, reptiles, amphibians, fish,
   insects, arachnids or other.
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
    text, i, o = complete(species_prompt(tally, notes, lang, context, known), max_tokens=3500, json_mode=True)
    return _json(text), i, o


def day_prompt(n: int, date_s: str, place: str, notes: str, species_lines: str, lang: str, tone: str, context: str) -> str:
    return f"""Write the Day {n} section of a wildlife trip report that a tour operator will send to its guests.

Style: {TONES.get(tone, TONES['warm'])}.
Language: {LANG_NAMES.get(lang, 'English')}.
Length: 120 to 220 words in 1 to 3 short paragraphs. Plain text only: no heading, no bullet points, no emoji, no markdown.
Voice: first person plural ("we").

Hard rules. Breaking any of these is a serious error:
1. Use only facts found in the guide's notes and the species list. Do not invent sightings, behaviour, weather, times, places, people, names or numbers.
2. Mention only species on the list. A species marked [UNCONFIRMED] must be described as possible or probable, never as certain. A species marked [heard only] was heard, not seen.
3. Don't try to mention every species; the report ends with a full checklist. Focus on what the notes treat as the highlights.
4. If the notes are thin, write a shorter section rather than padding it.
5. The notes may contain spelling mistakes and dictation errors. Understand what the guide meant and write it
   correctly, with species names spelled properly, but never change a fact, number or time.

{context}
Day {n}{', ' + date_s if date_s else ''}{', ' + place if place else ''}

Guide's notes:
\"\"\"
{notes[:8000] or '(none)'}
\"\"\"

Species list for this day:
{species_lines or '(no species listed)'}"""


def draft_day(**kw) -> tuple[str, int, int]:
    return complete(day_prompt(**kw), max_tokens=900)


def intro_prompt(days_text: str, n_days: int, n_species: int, guests, lang: str, tone: str, context: str) -> str:
    return f"""Write the opening and closing paragraphs of a wildlife trip report a tour operator sends to its guests.

Style: {TONES.get(tone, TONES['warm'])}. Language: {LANG_NAMES.get(lang, 'English')}. First person plural ("we"). Plain text, no emoji, no markdown.
- "intro": 50 to 100 words. Welcome the reader back to the trip: where it was, how many days, the feel of it. Don't list species.
- "summary": 50 to 110 words. Look back on the highlights, mention that {n_species} species were recorded, and thank the guests. No sign-off or names.
Use only facts from the day reports below. Species the day reports call possible or probable must stay that way.

{context}
Guests: {guests or '(not given)'}
Days: {n_days}

Day reports:
\"\"\"
{days_text[:20000]}
\"\"\"

Reply with only JSON: {{"intro":"...","summary":"..."}}"""


def draft_intro(**kw) -> tuple[dict, int, int]:
    text, i, o = complete(intro_prompt(**kw), max_tokens=900, json_mode=True)
    d = _json(text)
    if not isinstance(d, dict) or not isinstance(d.get("intro"), str):
        raise AIError("bad_output")
    return d, i, o


def season_prompt(facts: dict, lang: str, tone: str) -> str:
    return f"""Write a short season summary (90 to 140 words) that a wildlife tour operator can put on its website or in a newsletter.
Language: {LANG_NAMES.get(lang, 'English')}. First person plural ("we"). Plain text, 1 or 2 paragraphs, no heading, no emoji, no markdown.
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
