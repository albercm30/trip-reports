"""Stripe subscriptions: Checkout for new subscriptions, the Customer Portal for changes and
cancellations, and webhooks to keep each organization's plan in sync."""
from __future__ import annotations

import json
import logging
from datetime import datetime, timezone

from sqlalchemy import select
from sqlalchemy.orm import Session

from ..config import settings
from ..models import Organization, StripeEvent

log = logging.getLogger("tripreports.billing")


class BillingError(Exception):
    pass


def client():
    if not settings.billing_enabled:
        raise BillingError("not_configured")
    import stripe
    return stripe.StripeClient(settings.stripe_secret_key)


def _d(obj) -> dict:
    """Stripe objects -> plain dicts."""
    if obj is None:
        return {}
    if isinstance(obj, dict):
        return obj
    return obj.to_dict() if hasattr(obj, "to_dict") else dict(obj)


def plan_for_price(price_id: str) -> str | None:
    for (plan, _interval), pid in settings.stripe_prices.items():
        if pid == price_id:
            return plan
    return None


def checkout_url(org: Organization, email: str, plan: str, interval: str) -> str:
    price = settings.stripe_prices.get((plan, interval))
    if not price:
        raise BillingError("no_price")
    params = {
        "mode": "subscription",
        "line_items": [{"price": price, "quantity": 1}],
        "client_reference_id": org.id,
        "metadata": {"org_id": org.id},
        "subscription_data": {"metadata": {"org_id": org.id}},
        "allow_promotion_codes": True,
        "billing_address_collection": "required",
        "tax_id_collection": {"enabled": True},
        # Stripe fills in {CHECKOUT_SESSION_ID}; the billing page uses it to confirm the plan right away.
        "success_url": f"{settings.app_url}/app/billing?done=1&session_id={{CHECKOUT_SESSION_ID}}",
        "cancel_url": f"{settings.app_url}/app/billing",
    }
    if org.stripe_customer_id:
        params["customer"] = org.stripe_customer_id
        params["customer_update"] = {"address": "auto", "name": "auto"}
    else:
        params["customer_email"] = email
    s = client().v1.checkout.sessions.create(params=params)
    return _d(s)["url"]


def portal_url(org: Organization) -> str:
    if not org.stripe_customer_id:
        raise BillingError("no_customer")
    s = client().v1.billing_portal.sessions.create(params={
        "customer": org.stripe_customer_id, "return_url": f"{settings.app_url}/app/billing"})
    return _d(s)["url"]


def cancel_now(org: Organization) -> None:
    """Used when an owner deletes the organization."""
    if not org.stripe_subscription_id or not settings.billing_enabled:
        return
    try:
        client().v1.subscriptions.cancel(org.stripe_subscription_id)
    except Exception as e:
        log.warning("Could not cancel subscription %s: %s", org.stripe_subscription_id, e)


def _ts(v) -> datetime | None:
    return datetime.fromtimestamp(int(v), tz=timezone.utc) if v else None


def apply_subscription(db: Session, sub: dict) -> Organization | None:
    meta = sub.get("metadata") or {}
    org = db.get(Organization, meta["org_id"]) if meta.get("org_id") else None
    if org is None and sub.get("customer"):
        org = db.scalar(select(Organization).where(Organization.stripe_customer_id == sub["customer"]))
    if org is None:
        log.warning("Subscription %s has no matching organization", sub.get("id"))
        return None
    items = (sub.get("items") or {}).get("data") or []
    item = items[0] if items else {}
    plan = plan_for_price((item.get("price") or {}).get("id", ""))
    org.stripe_subscription_id = sub.get("id")
    if sub.get("customer"):
        org.stripe_customer_id = sub["customer"]
    org.billing_status = sub.get("status", "incomplete")
    if plan:
        org.plan = plan
    org.current_period_end = _ts(sub.get("current_period_end") or item.get("current_period_end"))
    # Cancelling in the portal usually means "at the end of the period": the subscription stays
    # active until then, so remember the date to show it.
    if sub.get("status") in ("canceled", "incomplete_expired"):
        org.cancel_at = None
    elif sub.get("cancel_at"):
        org.cancel_at = _ts(sub["cancel_at"])
    elif sub.get("cancel_at_period_end"):
        org.cancel_at = org.current_period_end
    else:
        org.cancel_at = None
    return org


def sync_checkout(db: Session, org: Organization, session_id: str) -> bool:
    """Confirm a finished checkout straight from Stripe, so the plan shows as active even if the
    webhook is slow or misconfigured. Only applies sessions that belong to this organization."""
    s = _d(client().v1.checkout.sessions.retrieve(session_id, params={"expand": ["subscription"]}))
    if (s.get("client_reference_id") or (s.get("metadata") or {}).get("org_id")) != org.id:
        return False
    if s.get("customer"):
        org.stripe_customer_id = s["customer"]
    sub = s.get("subscription")
    if isinstance(sub, str):
        sub = _d(client().v1.subscriptions.retrieve(sub))
    if sub:
        apply_subscription(db, {**sub, "metadata": {**(sub.get("metadata") or {}), "org_id": org.id}})
    db.commit()
    return bool(sub)


def sync_customer(db: Session, org: Organization) -> bool:
    """Re-read this organization's latest subscription from Stripe."""
    if not org.stripe_customer_id:
        return False
    subs = _d(client().v1.subscriptions.list(params={"customer": org.stripe_customer_id, "status": "all", "limit": 1}))
    data = subs.get("data") or []
    if not data:
        return False
    apply_subscription(db, {**data[0], "metadata": {**(data[0].get("metadata") or {}), "org_id": org.id}})
    db.commit()
    return True


def handle_event(db: Session, payload: bytes, sig_header: str) -> str:
    """Verify and apply a Stripe webhook. Returns a short status string. Raises ValueError if invalid."""
    import stripe
    try:
        stripe.WebhookSignature.verify_header(payload.decode("utf-8"), sig_header, settings.stripe_webhook_secret, 300)
    except Exception as e:
        raise ValueError("bad signature") from e
    event = json.loads(payload)
    eid, etype = event.get("id", ""), event.get("type", "")
    if db.get(StripeEvent, eid):
        return "duplicate"
    obj = (event.get("data") or {}).get("object") or {}
    if etype == "checkout.session.completed" and obj.get("mode") == "subscription":
        org = db.get(Organization, obj.get("client_reference_id") or (obj.get("metadata") or {}).get("org_id", ""))
        if org:
            org.stripe_customer_id = obj.get("customer") or org.stripe_customer_id
            if obj.get("subscription"):
                org.stripe_subscription_id = obj["subscription"]
                try:
                    apply_subscription(db, _d(client().v1.subscriptions.retrieve(obj["subscription"])))
                except Exception as e:  # the subscription.* events will sync it anyway
                    log.warning("Could not fetch subscription after checkout: %s", e)
    elif etype in ("customer.subscription.created", "customer.subscription.updated",
                   "customer.subscription.deleted", "customer.subscription.paused", "customer.subscription.resumed"):
        if etype == "customer.subscription.deleted":
            obj = {**obj, "status": "canceled"}
        apply_subscription(db, obj)
    elif etype == "invoice.payment_failed":
        cust = obj.get("customer")
        org = db.scalar(select(Organization).where(Organization.stripe_customer_id == cust)) if cust else None
        if org and org.billing_status == "active":
            org.billing_status = "past_due"
    db.add(StripeEvent(id=eid))
    db.commit()
    return etype
