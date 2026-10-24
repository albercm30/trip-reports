"""Interface language (English / Spanish). Strings are written in English in the code and
templates; app/locales/es.json maps them to Spanish. Missing translations fall back to English."""
from __future__ import annotations

import json
from functools import lru_cache
from pathlib import Path

from fastapi import Request

UI_LANGS = {"en": "English", "es": "Español"}
LOCALES = Path(__file__).parent / "locales"


@lru_cache
def catalog(lang: str) -> dict:
    p = LOCALES / f"{lang}.json"
    return json.loads(p.read_text(encoding="utf-8")) if p.is_file() else {}


def translate(lang: str, text: str, **kw) -> str:
    s = catalog(lang).get(text, text) if lang != "en" else text
    if kw:
        try:
            s = s.format(**kw)
        except (KeyError, IndexError, ValueError):
            s = text.format(**kw)
    return s


def detect_lang(request: Request, user=None) -> str:
    if user is not None and getattr(user, "ui_lang", None) in UI_LANGS:
        return user.ui_lang
    q = request.query_params.get("lang")
    if q in UI_LANGS:
        return q
    c = request.cookies.get("lang")
    if c in UI_LANGS:
        return c
    al = request.headers.get("accept-language", "").lower()
    return "es" if al.startswith("es") or (",es" in al and not al.startswith("en")) else "en"
