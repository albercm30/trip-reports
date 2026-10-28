from datetime import datetime, timedelta, timezone

import httpx

from app import plans
from app.config import settings
from app.db import SessionLocal
from app.models import Organization
from app.services import mail

from .conftest import signup


def _org():
    with SessionLocal() as db:
        return db.query(Organization).one()


def _expire_trial():
    with SessionLocal() as db:
        o = db.query(Organization).one()
        o.trial_ends_at = datetime.now(timezone.utc) - timedelta(days=1)
        db.commit()


def test_admin_page_is_hidden_from_everyone_else(owner):
    assert owner.get("/app/admin").status_code == 404
    assert "/app/admin" not in owner.get("/app").text


def test_admin_turns_on_a_pilot_that_never_expires(client, monkeypatch):
    monkeypatch.setattr(settings, "admin_emails", ("owner@example.com",))
    signup(client)
    _expire_trial()
    assert not plans.can_write(_org())
    page = client.get("/app/admin")
    assert page.status_code == 200 and "Sierra Tours" in page.text
    org_id = _org().id
    r = client.post_form(f"/app/admin/{org_id}/pilot")
    assert r.status_code == 303
    o = _org()
    assert o.plan == "pilot" and plans.can_write(o)
    billing = client.get("/app/billing").text
    assert "Pilot company" in billing and "Choose a plan" not in billing
    client.post_form(f"/app/admin/{org_id}/trial")
    o = _org()
    assert o.plan == "trial" and plans.trial_days_left(o) == settings.trial_days


def test_brevo_sends_over_https(monkeypatch):
    sent = {}

    def fake_post(url, json=None, headers=None, timeout=None):
        sent.update(url=url, json=json, headers=headers)
        return httpx.Response(201, json={"messageId": "x"})

    monkeypatch.setattr(settings, "brevo_api_key", "xkeysib-test")
    monkeypatch.setattr(settings, "mail_from", "hola@example.com")
    monkeypatch.setattr(mail.httpx, "post", fake_post)
    assert mail.send("guide@example.com", "Hola", "Texto")
    assert sent["url"] == mail.BREVO_URL and sent["headers"]["api-key"] == "xkeysib-test"
    assert sent["json"]["to"] == [{"email": "guide@example.com"}] and sent["json"]["sender"]["email"] == "hola@example.com"


def test_legal_pages_show_the_owner(client, monkeypatch):
    monkeypatch.setattr(settings, "legal_name", "Ana Pérez")
    monkeypatch.setattr(settings, "legal_address", "Calle Mayor 1, Madrid")
    for url in ("/privacy", "/terms"):
        t = client.get(url).text
        assert "Ana Pérez" in t and "Calle Mayor 1" in t and "[LEGAL NAME]" not in t
