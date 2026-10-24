import hashlib
import hmac
import json
import time
from datetime import datetime, timedelta, timezone

from app import plans
from app.db import SessionLocal
from app.models import Organization
from app.services import billing


def _signed(payload: dict, secret="whsec_test"):
    body = json.dumps(payload)
    ts = int(time.time())
    sig = hmac.new(secret.encode(), f"{ts}.{body}".encode(), hashlib.sha256).hexdigest()
    return body, f"t={ts},v1={sig}"


def _org():
    with SessionLocal() as db:
        return db.query(Organization).one()


def _sub(org_id, status="active", price="price_starter_m", sub_id="sub_1"):
    end = int((datetime.now(timezone.utc) + timedelta(days=30)).timestamp())
    return {"id": sub_id, "object": "subscription", "customer": "cus_1", "status": status, "metadata": {"org_id": org_id},
            "items": {"data": [{"price": {"id": price}, "current_period_end": end}]}}


def test_webhook_rejects_bad_signature(owner):
    body, _ = _signed({"id": "evt_1", "type": "customer.subscription.updated"})
    r = owner.post("/billing/webhook", content=body, headers={"stripe-signature": "t=1,v1=bad"})
    assert r.status_code == 400


def test_subscription_lifecycle(owner):
    org = _org()
    body, sig = _signed({"id": "evt_1", "type": "customer.subscription.created",
                         "data": {"object": _sub(org.id)}})
    r = owner.post("/billing/webhook", content=body, headers={"stripe-signature": sig})
    assert r.status_code == 200
    org = _org()
    assert org.plan == "starter" and org.billing_status == "active" and org.stripe_customer_id == "cus_1"
    assert org.current_period_end is not None and plans.can_write(org)

    # duplicate delivery is ignored
    r = owner.post("/billing/webhook", content=body, headers={"stripe-signature": sig})
    assert r.json()["type"] == "duplicate"

    # upgrade to pro
    body, sig = _signed({"id": "evt_2", "type": "customer.subscription.updated",
                         "data": {"object": _sub(org.id, price="price_pro_m")}})
    owner.post("/billing/webhook", content=body, headers={"stripe-signature": sig})
    assert _org().plan == "pro"

    # failed payment keeps access (grace), cancellation removes write access
    body, sig = _signed({"id": "evt_3", "type": "invoice.payment_failed", "data": {"object": {"customer": "cus_1"}}})
    owner.post("/billing/webhook", content=body, headers={"stripe-signature": sig})
    assert _org().billing_status == "past_due" and plans.can_write(_org())
    body, sig = _signed({"id": "evt_4", "type": "customer.subscription.deleted",
                         "data": {"object": _sub(org.id, status="canceled")}})
    owner.post("/billing/webhook", content=body, headers={"stripe-signature": sig})
    org = _org()
    assert org.billing_status == "canceled" and not plans.can_write(org)


def test_checkout_redirects_to_stripe(owner, monkeypatch):
    seen = {}

    def fake(org, email, plan, interval):
        seen.update(plan=plan, interval=interval, email=email)
        return "https://checkout.stripe.com/c/pay/test"
    monkeypatch.setattr(billing, "checkout_url", fake)
    r = owner.post_form("/app/billing/checkout", {"plan": "pro", "interval": "month"})
    assert r.status_code == 303 and r.headers["location"].startswith("https://checkout.stripe.com/")
    assert seen == {"plan": "pro", "interval": "month", "email": "owner@example.com"}


def test_checkout_without_price_shows_message(owner):
    r = owner.post_form("/app/billing/checkout", {"plan": "pro", "interval": "year"})
    assert r.status_code == 303 and r.headers["location"] == "/app/billing"


def test_billing_page_renders(owner):
    page = owner.get("/app/billing").text
    assert "Free trial" in page and "Choose a plan" in page
