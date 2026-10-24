"""Optional Claude (Anthropic API) drafting. Only used when ANTHROPIC_API_KEY is set.

Every prompt carries the same hard rule: use only the guide's notes and species list,
never invent sightings. The guide still approves every day before guests see it.
"""
from __future__ import annotations

import json
import logging
import re

from ..config import settings

log = logging.getLogger("tripreports.ai")

LANG_NAMES = {"en": "English", "es": "Spanish", "de": "German", "fr": "French"}
TONES = {
    "warm": "warm, personal and vivid, like a friendly guide writing to guests they enjoyed spending time with",
    "expert": "knowledgeable and precise, like an experienced naturalist; calm, factual, with small ecological details only where the notes support them",
    "lively": "upbeat and lively with light humour, but never silly or exaggerated",
}
SYSTEM = ("You help wildlife and birding tour guides write trip reports for their guests. "
          "You only ever use facts the guide gave you. You never invent animals, sightings, numbers, "
          "times, places, people or weather.")


class AIError(Exception):
    def __init__(self, code: str):
        super().__init__(code)
        self.code = code  # unavailable | rate_limited | refused | bad_output | too_long


_client = None


def _get_client():
    global _client
    if _client is None:
        import anthropic  # imported lazily so the app runs without the package or a key
        _client = anthropic.Anthropic(api_key=settings.anthropic_api_key, max_retries=2, timeout=60)
    return _client


def complete(prompt: str, *, fast: bool = False, max_tokens: int = 1200) -> tuple[str, int, int]:
    """Returns (text, input_tokens, output_tokens). Raises AIError."""
    if not settings.ai_enabled:
        raise AIError("unavailable")
    try:
        import anthropic
        resp = _get_client().messages.create(
            model=settings.anthropic_fast_model if fast else settings.anthropic_model,
            max_tokens=max_tokens, system=SYSTEM,
            messages=[{"role": "user", "content": prompt}])
    except ImportError as e:
        raise AIError("unavailable") from e
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
    if not text:
        raise AIError("bad_output")
    u = getattr(resp, "usage", None)
    return text, getattr(u, "input_tokens", 0) or 0, getattr(u, "output_tokens", 0) or 0


def _json(text: str):
    m = re.search(r"(\[.*\]|\{.*\})", text, re.S)
    if not m:
        raise AIError("bad_output")
    try:
        return json.loads(m.group(1))
    except json.JSONDecodeError as e:
        raise AIError("bad_output") from e


def species_prompt(raw: str, lang: str, context: str) -> str:
    ln = LANG_NAMES.get(lang, "English")
    return f"""Turn this wildlife guide's rough field tally into a clean species list.
{context}
Write common names in {ln}.

Rules:
- Include ONLY animals explicitly written in the notes. Never add a species that isn't mentioned.
- Correct spelling to the standard common name for this region and add the scientific name.
- If an entry is vague ("eagle", "some warblers", "a raptor") or you are not confident which species it is, keep the guide's wording as "name", set "sci" to "" and "sure" to false.
- If the guide marks doubt ("?", "probably", "possible"), set "sure" to false but still give your best scientific name.
- "count": the number given, or null if none. "pair" means 2.
- "heard": true only if the notes say it was heard and not seen.
- "star": true only if the guide marked it with "!" or called it a highlight.
- "group": one of "birds", "mammals", "reptiles", "amphibians", "fish", "insects", "arachnids", "other".

Reply with only a JSON array like:
[{{"name":"Griffon Vulture","sci":"Gyps fulvus","count":40,"heard":false,"sure":true,"star":false,"group":"birds"}}]

Guide's notes:
\"\"\"
{raw[:6000]}
\"\"\""""


def parse_species(raw: str, lang: str, context: str) -> tuple[list, int, int]:
    text, i, o = complete(species_prompt(raw, lang, context), fast=True, max_tokens=3000)
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
    text, i, o = complete(intro_prompt(**kw), max_tokens=900)
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
