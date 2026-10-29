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
from ..services.demo_marine import build_marine_trip
from ..services import species_images
from ..services.reportdata import build_report
from ..web import render

router = APIRouter()


@router.get("/")
def landing(request: Request, user=Depends(optional_user)):
    return render(request, "public/landing.html", {"plans": plans.PLANS}, user=user)


@router.get("/example")
def example(request: Request, db: Session = Depends(get_db), user=Depends(optional_user)):
    from ..i18n import detect_lang
    lang = request.query_params.get("rl") or detect_lang(request, user)
    lang = lang if lang in ("en", "es") else "en"
    if request.query_params.get("kind") == "marine":
        trip = build_marine_trip(lang)
        org = SimpleNamespace(name="Cetáceos de La Palma (ejemplo)" if lang == "es" else "La Palma Whale Watching (example)",
                              accent="#1f5f7a", report_lang=lang, website="www.example.com",
                              signoff="Gracias por navegar con nosotros.\nLaura, Dani y el equipo" if lang == "es"
                              else "Thank you for sailing with us.\nLaura, Dani and the team",
                              show_credit=True, logo_key=None)
    else:
        trip = build_example_trip(lang, "Alberto")
        org = SimpleNamespace(name="Sierra Morena Wildlife Tours" if lang == "en" else "Sierra Morena Naturaleza",
                              accent="#2E6A5C", report_lang=lang, website="www.example.com",
                              signoff="Thank you for travelling with us.\nAlberto and the team" if lang == "en"
                              else "Gracias por viajar con nosotros.\nAlberto y el equipo",
                              show_credit=True, logo_key=None)
    return render(request, "report/page.html", {"trip": trip, "rorg": org, "R": build_report(trip, org, settings.name_for(org.report_lang), species_images.for_trip(db, trip, org)),
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


# ---------------------------------------------------------------- installable app (PWA)
@router.get("/manifest.webmanifest")
def manifest(request: Request, user=Depends(optional_user)):
    from fastapi.responses import JSONResponse
    from ..i18n import detect_lang
    lang = detect_lang(request, user)
    name = settings.name_for(lang)
    return JSONResponse({
        "name": name, "short_name": name if len(name) <= 14 else name.split()[0],
        "description": "Trip reports for wildlife guides" if lang != "es" else "Informes de salidas para guías de naturaleza",
        "lang": lang, "start_url": "/app", "scope": "/", "display": "standalone",
        "background_color": "#F2F3EE", "theme_color": "#2E6A5C",
        "icons": [
            {"src": "/static/img/icon-192.png", "sizes": "192x192", "type": "image/png"},
            {"src": "/static/img/icon-512.png", "sizes": "512x512", "type": "image/png"},
            {"src": "/static/img/icon-maskable-512.png", "sizes": "512x512", "type": "image/png", "purpose": "maskable"},
        ],
    }, media_type="application/manifest+json", headers={"Cache-Control": "public, max-age=3600"})


@router.get("/offline")
def offline(request: Request, user=Depends(optional_user)):
    resp = render(request, "public/offline.html")
    resp.headers["Cache-Control"] = "no-cache"
    return resp


SW = """// Service worker: lets guides install the app, keeps the look (styles, scripts, icons) cached, and
// opens the "no signal" page (record voice notes, save GPS positions) when there's no connection.
// Pages and data always come from the network, so nothing private is stored by it.
const CACHE = "static-v2";
const OFFLINE = ["/offline", "/static/js/field.js?v=1", "/static/css/app.css?v=5", "/static/img/icon.svg"];
self.addEventListener("install", e => e.waitUntil(
  caches.open(CACHE).then(c => c.addAll(OFFLINE)).catch(() => null).then(() => self.skipWaiting())));
self.addEventListener("activate", e => e.waitUntil(
  caches.keys().then(ks => Promise.all(ks.filter(k => k !== CACHE).map(k => caches.delete(k)))).then(() => self.clients.claim())));
self.addEventListener("fetch", e => {
  const url = new URL(e.request.url);
  if (e.request.method !== "GET" || url.origin !== location.origin) return;
  if (url.pathname.startsWith("/static/")) {
    e.respondWith(caches.open(CACHE).then(c => c.match(e.request).then(hit => {
      const net = fetch(e.request).then(r => { if (r.ok) c.put(e.request, r.clone()); return r; }).catch(() => hit);
      return hit || net;
    })));
    return;
  }
  if (e.request.mode === "navigate") {
    e.respondWith(fetch(e.request).then(r => {
      if (url.pathname === "/offline" && r.ok) caches.open(CACHE).then(c => c.put("/offline", r.clone()));
      return r;
    }).catch(() => caches.match("/offline").then(hit => hit || new Response(
      '<!doctype html><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">' +
      '<body style="font-family:system-ui,sans-serif;padding:32px"><h1>Sin conexión · Offline</h1>' +
      '<p>Vuelve a intentarlo cuando tengas cobertura. Try again when you have signal.</p></body>',
      {headers: {"Content-Type": "text/html; charset=utf-8"}}))));
  }
});
"""


@router.get("/sw.js")
def service_worker():
    from fastapi.responses import Response
    return Response(SW, media_type="application/javascript",
                    headers={"Cache-Control": "no-cache", "Service-Worker-Allowed": "/"})
