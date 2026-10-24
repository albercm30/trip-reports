from __future__ import annotations

import logging

from fastapi import APIRouter, Depends, Form, Request
from fastapi.responses import JSONResponse, RedirectResponse
from sqlalchemy.orm import Session

from .. import plans
from ..config import settings
from ..db import get_db
from ..deps import current_user, owner
from ..models import User
from ..services import billing as svc
from ..web import redirect, render

router = APIRouter(prefix="/app/billing")
webhook_router = APIRouter()
log = logging.getLogger("tripreports.billing")


@router.get("")
def billing_page(request: Request, db: Session = Depends(get_db), user: User = Depends(current_user)):
    org = user.org
    return render(request, "app/billing.html", {
        "nav": "billing", "can_write": plans.can_write(org), "trial_left": plans.trial_days_left(org),
        "trial_active": plans.trial_active(org), "ai_used": plans.ai_used_this_month(db, org),
        "plan": plans.plan_of(org), "PLANS": plans.PLANS, "done": request.query_params.get("done") == "1",
        "available": {k for k, _ in settings.stripe_prices.keys()},
        "intervals": {i for _, i in settings.stripe_prices.keys()},
    }, user=user)


@router.post("/checkout")
def checkout(request: Request, user: User = Depends(owner), plan: str = Form("starter"), interval: str = Form("month")):
    if plan not in ("starter", "pro") or interval not in ("month", "year"):
        return redirect("/app/billing")
    try:
        url = svc.checkout_url(user.org, user.email, plan, interval)
    except svc.BillingError as e:
        msg = "Payments aren't set up yet." if str(e) in ("not_configured", "no_price") else "Couldn't start checkout."
        return redirect("/app/billing", msg)
    except Exception as e:
        log.exception("Stripe checkout failed: %s", e)
        return redirect("/app/billing", "Couldn't reach the payment provider. Try again in a minute.")
    return RedirectResponse(url, status_code=303)


@router.post("/portal")
def portal(request: Request, user: User = Depends(owner)):
    try:
        url = svc.portal_url(user.org)
    except svc.BillingError:
        return redirect("/app/billing", "There's no subscription to manage yet.")
    except Exception as e:
        log.exception("Stripe portal failed: %s", e)
        return redirect("/app/billing", "Couldn't reach the payment provider. Try again in a minute.")
    return RedirectResponse(url, status_code=303)


@webhook_router.post("/billing/webhook", include_in_schema=False)
async def webhook(request: Request, db: Session = Depends(get_db)):
    if not settings.stripe_webhook_secret:
        return JSONResponse({"error": "not configured"}, status_code=400)
    payload = await request.body()
    try:
        result = svc.handle_event(db, payload, request.headers.get("stripe-signature", ""))
    except ValueError:
        return JSONResponse({"error": "invalid signature"}, status_code=400)
    return JSONResponse({"received": True, "type": result})
