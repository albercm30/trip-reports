from __future__ import annotations

from types import SimpleNamespace

from fastapi import APIRouter, Depends, Request
from fastapi.responses import RedirectResponse
from sqlalchemy.orm import Session

from .. import plans
from ..config import settings
from ..db import get_db
from ..deps import optional_user
from ..security import user_from_request
from ..i18n import UI_LANGS
from ..services.demo import build_example_trip
from ..services.reportdata import build_report
from ..web import render

router = APIRouter()


@router.get("/")
def landing(request: Request, user=Depends(optional_user)):
    return render(request, "public/landing.html", {"plans": plans.PLANS}, user=user)


@router.get("/example")
def example(request: Request, user=Depends(optional_user)):
    from ..i18n import detect_lang
    lang = request.query_params.get("rl") or detect_lang(request, user)
    lang = lang if lang in ("en", "es") else "en"
    trip = build_example_trip(lang, "Alberto")
    org = SimpleNamespace(name="Sierra Morena Wildlife Tours" if lang == "en" else "Sierra Morena Naturaleza",
                          accent="#2E6A5C", report_lang=lang, website="www.example.com",
                          signoff="Thank you for travelling with us.\nAlberto and the team" if lang == "en"
                          else "Gracias por viajar con nosotros.\nAlberto y el equipo",
                          show_credit=True, logo_key=None)
    return render(request, "report/page.html", {"trip": trip, "rorg": org, "R": build_report(trip, org, settings.app_name),
                                                 "example": True, "media_qs": ""}, user=user)


@router.get("/lang/{code}")
def set_lang(code: str, request: Request, db: Session = Depends(get_db)):
    from urllib.parse import urlparse
    ref = urlparse(request.headers.get("referer") or "/")
    back = (ref.path or "/") + (f"?{ref.query}" if ref.query and "lang=" not in ref.query else "")
    if not back.startswith("/") or back.startswith("//"):
        back = "/"
    resp = RedirectResponse(back, status_code=303)
    if code in UI_LANGS:
        u = user_from_request(db, request)
        if u:
            u.ui_lang = code
            db.commit()
        resp.set_cookie("lang", code, max_age=365 * 86400, samesite="lax", path="/")
    return resp


@router.get("/privacy")
def privacy(request: Request, user=Depends(optional_user)):
    return render(request, "public/privacy.html", user=user)


@router.get("/terms")
def terms(request: Request, user=Depends(optional_user)):
    return render(request, "public/terms.html", user=user)
