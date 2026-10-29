"""Voice notes recorded on the boat (no coverage needed) and turned into text when the phone is back
online. Free: Whisper on Groq (same LLM_API_KEY), with Cloudflare Workers AI's Whisper as the overflow.

Whisper is given the company's target species and the day's species as a hint, so names like
"calderón tropical" or "pardela cenicienta" come out spelled right."""
from __future__ import annotations

import base64
import logging
import re

import httpx

from ..config import settings

log = logging.getLogger("tripreports.voice")
MAX_AUDIO = 15 * 1024 * 1024  # about 15 minutes of phone audio; Groq's free limit is 25 MB
GROQ_MODELS = ["whisper-large-v3-turbo", "whisper-large-v3"]
CF_MODEL = "@cf/openai/whisper-large-v3-turbo"
EXT = {"audio/webm": "webm", "audio/ogg": "ogg", "audio/mp4": "m4a", "audio/x-m4a": "m4a", "audio/aac": "m4a",
       "audio/mpeg": "mp3", "audio/wav": "wav", "audio/x-wav": "wav", "video/webm": "webm", "video/mp4": "mp4"}


class VoiceError(Exception):
    pass


def enabled() -> bool:
    groq = bool(settings.llm_api_key and "groq.com" in settings.llm_base_url)
    return groq or bool(settings.cf_account_id and settings.cf_api_token)


def _hint(words: list[str]) -> str:
    """A short vocabulary prompt (Whisper reads at most ~224 tokens of it)."""
    seen, out = set(), []
    for w in words:
        w = w.strip()
        if w and w.lower() not in seen:
            seen.add(w.lower())
            out.append(w)
    return ", ".join(out)[:600]


def _groq(audio: bytes, mime: str, lang: str | None, prompt: str) -> str:
    ext = EXT.get(mime.split(";")[0].strip().lower(), "webm")
    last = None
    for model in GROQ_MODELS:
        data = {"model": model, "response_format": "json", "temperature": "0"}
        if lang:
            data["language"] = lang
        if prompt:
            data["prompt"] = prompt
        try:
            r = httpx.post(f"{settings.llm_base_url}/audio/transcriptions", data=data,
                           files={"file": (f"note.{ext}", audio, mime.split(";")[0] or "audio/webm")},
                           headers={"Authorization": f"Bearer {settings.llm_api_key}"}, timeout=90)
        except httpx.HTTPError as e:
            last = e
            continue
        if r.status_code == 200:
            return (r.json().get("text") or "").strip()
        last = f"{r.status_code} {r.text[:200]}"
        if r.status_code not in (404, 429, 500, 502, 503):
            break
    raise VoiceError(f"groq: {last}")


def _cloudflare(audio: bytes, lang: str | None, prompt: str) -> str:
    body = {"audio": base64.b64encode(audio).decode()}
    if lang:
        body["language"] = lang
    if prompt:
        body["initial_prompt"] = prompt
    r = httpx.post(f"https://api.cloudflare.com/client/v4/accounts/{settings.cf_account_id}/ai/run/{CF_MODEL}",
                   json=body, headers={"Authorization": f"Bearer {settings.cf_api_token}"}, timeout=120)
    if r.status_code != 200:
        raise VoiceError(f"cloudflare: {r.status_code} {r.text[:200]}")
    res = r.json().get("result") or {}
    return (res.get("text") or "").strip()


def transcribe(audio: bytes, mime: str = "audio/webm", lang: str | None = None, words: list[str] | None = None) -> str:
    if not audio:
        raise VoiceError("empty")
    if len(audio) > MAX_AUDIO:
        raise VoiceError("too_large")
    lang = lang if lang in ("es", "en", "de", "fr") else None
    prompt = _hint(words or [])
    errors = []
    if settings.llm_api_key and "groq.com" in settings.llm_base_url:
        try:
            return tidy(_groq(audio, mime, lang, prompt), prompt)
        except VoiceError as e:
            errors.append(str(e))
    if settings.cf_account_id and settings.cf_api_token:
        try:
            return tidy(_cloudflare(audio, lang, prompt), prompt)
        except (VoiceError, httpx.HTTPError, ValueError) as e:
            errors.append(str(e))
    log.warning("Voice note not transcribed: %s", "; ".join(errors) or "no speech-to-text service configured")
    raise VoiceError("unavailable")


def tidy(text: str, prompt: str = "") -> str:
    """Whisper sometimes returns the hint itself, or stock phrases, on silence: drop those."""
    t = " ".join((text or "").split())
    if not t:
        return ""
    if prompt and t.strip(" .").lower() == prompt.strip(" .").lower():
        return ""
    stock = r"^(subt[ií]tulos.*|gracias por ver.*|thanks? for watching.*|\[?m[uú]sica\]?|\.+)$"
    return "" if re.match(stock, t, re.I) else t
