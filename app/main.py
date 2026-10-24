from __future__ import annotations

import logging
import secrets
from pathlib import Path

from fastapi import Depends, FastAPI, HTTPException, Request
from fastapi.responses import JSONResponse, PlainTextResponse
from fastapi.staticfiles import StaticFiles
from starlette.exceptions import HTTPException as StarletteHTTPException

from .config import settings
from .deps import LoginRequired, NotFound, OwnerRequired, ReadOnly
from .security import CSRF_COOKIE, verify_csrf
from .web import redirect, render, wants_json

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
log = logging.getLogger("tripreports")

CSP = ("default-src 'self'; img-src 'self' data: blob: https:; style-src 'self' 'unsafe-inline' https://fonts.googleapis.com; "
       "font-src 'self' https://fonts.gstatic.com; script-src 'self'; connect-src 'self'; frame-ancestors 'none'; "
       "base-uri 'self'; form-action 'self' https://checkout.stripe.com https://billing.stripe.com")


def create_app() -> FastAPI:
    app = FastAPI(title=settings.app_name, docs_url=None, redoc_url=None, openapi_url=None)
    app.mount("/static", StaticFiles(directory=str(Path(__file__).parent / "static")), name="static")

    @app.middleware("http")
    async def security_headers(request: Request, call_next):
        request.state.csrf = request.cookies.get(CSRF_COOKIE) or secrets.token_urlsafe(24)
        response = await call_next(request)
        if not request.cookies.get(CSRF_COOKIE):
            response.set_cookie(CSRF_COOKIE, request.state.csrf, httponly=False, samesite="lax",
                                secure=settings.is_production, path="/", max_age=30 * 86400)
        h = response.headers
        h.setdefault("X-Content-Type-Options", "nosniff")
        h.setdefault("Referrer-Policy", "strict-origin-when-cross-origin")
        h.setdefault("X-Frame-Options", "DENY")
        h.setdefault("Content-Security-Policy", CSP)
        h.setdefault("Permissions-Policy", "camera=(), geolocation=(), microphone=(self)")
        if settings.is_production:
            h.setdefault("Strict-Transport-Security", "max-age=31536000; includeSubDomains")
        return response

    from .routes import account, app_pages, auth, billing, public, reports, settings_pages, trips

    guarded = [Depends(verify_csrf)]
    app.include_router(public.router, dependencies=guarded)
    app.include_router(auth.router, dependencies=guarded)
    app.include_router(app_pages.router, dependencies=guarded)
    app.include_router(trips.router, dependencies=guarded)
    app.include_router(reports.router, dependencies=guarded)
    app.include_router(settings_pages.router, dependencies=guarded)
    app.include_router(account.router, dependencies=guarded)
    app.include_router(billing.router, dependencies=guarded)
    app.include_router(billing.webhook_router)  # Stripe signs its own requests; no CSRF there

    @app.exception_handler(LoginRequired)
    async def _login(request: Request, exc):
        if wants_json(request):
            return JSONResponse({"ok": False, "error": "login"}, status_code=401)
        nxt = request.url.path if request.method == "GET" else "/app"
        return redirect(f"/login?next={nxt}")

    @app.exception_handler(OwnerRequired)
    async def _owner(request: Request, exc):
        return redirect("/app", "Only the account owner can do that.")

    @app.exception_handler(ReadOnly)
    async def _readonly(request: Request, exc):
        if wants_json(request):
            return JSONResponse({"ok": False, "error": "readonly"}, status_code=402)
        return redirect("/app/billing", "Your trial has ended. Choose a plan to keep creating and editing reports.")

    @app.exception_handler(NotFound)
    async def _nf(request: Request, exc):
        return render(request, "public/error.html", {"code": 404}, status=404)

    @app.exception_handler(StarletteHTTPException)
    async def _http(request: Request, exc: StarletteHTTPException):
        if exc.status_code == 403 and exc.detail == "csrf":
            if wants_json(request):
                return JSONResponse({"ok": False, "error": "csrf"}, status_code=403)
            return render(request, "public/error.html", {"code": 403, "csrf": True}, status=403)
        if wants_json(request):
            return JSONResponse({"ok": False, "error": exc.status_code}, status_code=exc.status_code)
        if exc.status_code in (404, 405):
            return render(request, "public/error.html", {"code": 404}, status=404)
        return render(request, "public/error.html", {"code": exc.status_code}, status=exc.status_code)

    @app.exception_handler(Exception)
    async def _err(request: Request, exc: Exception):
        log.exception("Unhandled error on %s %s", request.method, request.url.path)
        if wants_json(request):
            return JSONResponse({"ok": False, "error": "server"}, status_code=500)
        return render(request, "public/error.html", {"code": 500}, status=500)

    @app.get("/healthz", include_in_schema=False)
    def healthz():
        return PlainTextResponse("ok")

    @app.get("/robots.txt", include_in_schema=False)
    def robots():
        return PlainTextResponse("User-agent: *\nDisallow: /app\nDisallow: /r/\nDisallow: /media/\n")

    _ = HTTPException  # re-exported for routes
    return app


app = create_app()
