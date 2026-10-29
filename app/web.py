"""Template rendering, flash messages and request helpers shared by all routes."""
from __future__ import annotations

from pathlib import Path
from urllib.parse import quote, unquote

from fastapi import HTTPException, Request
from fastapi.responses import JSONResponse, RedirectResponse
from fastapi.templating import Jinja2Templates
from markupsafe import Markup

from . import plans
from .config import settings
from .i18n import UI_LANGS, detect_lang, translate
from .security import csrf_token

templates = Jinja2Templates(directory=str(Path(__file__).parent / "templates"))
FLASH = "flash"


def nl2p(text: str) -> Markup:
    from markupsafe import escape
    paras = [p.strip() for p in (text or "").replace("\r", "").split("\n") if p.strip()]
    return Markup("".join(f"<p>{escape(p)}</p>" for p in paras))


templates.env.filters["nl2p"] = nl2p

JS_STRINGS = ["Saving…", "Saved", "Not saved", "Unsaved changes", "Copied.", "Writing…",
              "Couldn't copy. Select the text and copy it yourself.", "Something went wrong. Try again.",
              "Your session ended. Log in again to keep saving.",
              "Your trial has ended. Choose a plan to keep editing.", "Write the day report before approving it.",
              "Drafted with AI. Edit before you publish it.",
              "Draft ready, built from your numbers. Edit before you publish it.",
              "Dictate", "Stop dictating", "Listening…", "Allow microphone access in your browser to dictate.",
              "Didn't hear anything. Try again closer to the microphone.", "Dictation needs an internet connection.",
              "Dictation stopped. Try again.", "Language you will speak",
              "This browser can't dictate in that language. Try Chrome, or another language."]
templates.env.globals.update(settings=settings, plans=plans, UI_LANGS=UI_LANGS)


OUTINGS = {
    "Trips": "Outings", "Trip": "Outing", "trips": "outings", "New trip": "New outing",
    "Start your own trip": "Start your first outing", "Untitled trip": "Untitled outing", "All trips": "All outings",
    "Trip name": "Outing name", "Delete trip": "Delete outing", "Trip reports": "Outing reports",
    "Write your first real trip": "Write your first real outing", "Insights need a few trips": "Insights need a few outings",
    "no trips": "no outings", "Recorded on only one trip": "Recorded on only one outing",
    "Built from {n} trips you've logged.": "Built from {n} outings you've logged.",
    "Striped months have no trips, and months with only one or two trips can swing a lot.":
        "Striped months have no outings, and months with only one or two outings can swing a lot.",
    "Delete this trip and everything in it? This can't be undone.":
        "Delete this outing and everything in it? This can't be undone.",
}


def render(request: Request, name: str, ctx: dict | None = None, *, user=None, status: int = 200):
    lang = detect_lang(request, user)
    single = bool(getattr(getattr(user, "org", None), "single_day", False))
    flash = request.cookies.get(FLASH)
    data = {
        "request": request, "lang": lang, "user": user, "org": getattr(user, "org", None),
        "csrf": csrf_token(request), "app_name": settings.name_for(lang),
        "_": lambda text, **kw: translate(lang, text, **kw),
        # wording that follows the company's activity: "trips" or single-day "outings"
        "t_": lambda text, **kw: translate(lang, OUTINGS.get(text, text) if single else text, **kw),
        "single_day": single,
        "flash": translate(lang, unquote(flash)) if flash else None,
        "js_strings": {k: translate(lang, k) for k in JS_STRINGS} if lang != "en" else {},
    }
    data.update(ctx or {})
    resp = templates.TemplateResponse(request, name, data, status_code=status)
    if flash:
        resp.delete_cookie(FLASH, path="/")
    return resp


def redirect(url: str, flash: str | None = None, status: int = 303) -> RedirectResponse:
    resp = RedirectResponse(url, status_code=status)
    if flash:
        resp.set_cookie(FLASH, quote(flash), max_age=60, httponly=True, samesite="lax", path="/")
    return resp


def wants_json(request: Request) -> bool:
    return request.headers.get("x-requested-with") == "fetch"


def ok_or_redirect(request: Request, url: str, flash: str | None = None, **extra):
    if wants_json(request):
        return JSONResponse({"ok": True, **extra})
    return redirect(url, flash)


def not_found() -> HTTPException:
    return HTTPException(status_code=404)
