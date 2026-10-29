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


def test_webhook_works_at_common_alternative_addresses(owner):
    org = _org()
    for i, path in enumerate(["/billing/webhook/", "/app/billing/webhook", "/stripe/webhook", "/webhook"]):
        body, sig = _signed({"id": f"evt_alias_{i}", "type": "customer.subscription.updated",
                             "data": {"object": _sub(org.id)}})
        r = owner.post(path, content=body, headers={"stripe-signature": sig})
        assert r.status_code == 200, path
    assert _org().billing_status == "active"


def test_wrong_post_address_gives_readable_json(owner):
    r = owner.post("/billing/webhooks", content="{}", headers={"accept": "*/*; q=0.5, application/json"})
    assert r.status_code == 404 and r.json()["path"] == "/billing/webhooks"


class _FakeObj(dict):
    def to_dict(self):
        return dict(self)


class _FakeClient:
    def __init__(self, org_id):
        sub = _sub(org_id)
        sub["metadata"] = {}
        self.sub = sub
        outer = self

        class Sessions:
            def retrieve(self, sid, params=None):
                assert params == {"expand": ["subscription"]}
                return _FakeObj({"id": sid, "client_reference_id": org_id, "customer": "cus_9", "subscription": outer.sub})

        class Subs:
            def list(self, params=None):
                return _FakeObj({"data": [{**outer.sub, "status": "past_due"}]})

            def retrieve(self, sid):
                return _FakeObj(outer.sub)

        class V1:
            checkout = type("C", (), {"sessions": Sessions()})()
            subscriptions = Subs()
        self.v1 = V1()


def test_return_from_checkout_activates_plan_without_webhook(owner, monkeypatch):
    org = _org()
    monkeypatch.setattr(billing, "client", lambda: _FakeClient(org.id))
    page = owner.get("/app/billing?done=1&session_id=cs_test_123").text
    org = _org()
    assert org.plan == "starter" and org.billing_status == "active" and org.stripe_customer_id == "cus_1"
    assert "Active" in page
    # someone else's session id is ignored
    other = _FakeClient("someone-else")
    monkeypatch.setattr(billing, "client", lambda: other)
    with SessionLocal() as db:
        o = db.get(Organization, org.id)
        assert billing.sync_checkout(db, o, "cs_x") is False
    # refresh button re-reads Stripe
    monkeypatch.setattr(billing, "client", lambda: _FakeClient(org.id))
    r = owner.post_form("/app/billing/sync")
    assert r.status_code == 303 and _org().billing_status == "past_due"


def test_cancel_at_period_end_is_shown(owner):
    org = _org()
    sub = _sub(org.id)
    body, sig = _signed({"id": "evt_c1", "type": "customer.subscription.created", "data": {"object": sub}})
    owner.post("/billing/webhook", content=body, headers={"stripe-signature": sig})
    sub2 = {**sub, "cancel_at_period_end": True}
    body, sig = _signed({"id": "evt_c2", "type": "customer.subscription.updated", "data": {"object": sub2}})
    owner.post("/billing/webhook", content=body, headers={"stripe-signature": sig})
    org = _org()
    assert org.billing_status == "active" and org.cancel_at is not None and plans.can_write(org)
    page = owner.get("/app/billing").text
    assert "Your plan ends on" in page
    # turning renewal back on clears it
    body, sig = _signed({"id": "evt_c3", "type": "customer.subscription.updated", "data": {"object": sub}})
    owner.post("/billing/webhook", content=body, headers={"stripe-signature": sig})
    assert _org().cancel_at is None and "Renews on" in owner.get("/app/billing").text


def test_prices_are_hidden_during_the_pilot(client):
    from .conftest import signup
    page = client.get("/").text
    assert "€29" not in page and "€59" not in page and "blurred" in page
    signup(client)
    page = client.get("/app/billing").text
    assert "€29" not in page and "/app/billing/checkout" not in page
