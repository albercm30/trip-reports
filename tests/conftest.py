import os
import re
import sys
import tempfile
from pathlib import Path

import pytest

_tmp = tempfile.mkdtemp(prefix="tripreports-test-")
os.environ.update({
    "APP_ENV": "test",
    "ENV_FILE": "/nonexistent",
    "DATABASE_URL": f"sqlite:///{_tmp}/test.db",
    "UPLOAD_DIR": f"{_tmp}/uploads",
    "SECRET_KEY": "test-secret",
    "GBIF_CHECK": "false",
    "ANTHROPIC_API_KEY": "",
    "STRIPE_SECRET_KEY": "sk_test_dummy",
    "STRIPE_WEBHOOK_SECRET": "whsec_test",
    "STRIPE_PRICE_STARTER_MONTHLY": "price_starter_m",
    "STRIPE_PRICE_PRO_MONTHLY": "price_pro_m",
    "APP_URL": "http://testserver",
})
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from fastapi.testclient import TestClient  # noqa: E402

from app.db import Base, engine  # noqa: E402
from app.main import app  # noqa: E402
from app import security  # noqa: E402


@pytest.fixture(autouse=True)
def fresh_db():
    Base.metadata.drop_all(engine)
    Base.metadata.create_all(engine)
    for lim in (security.login_limiter, security.signup_limiter, security.reset_limiter, security.ai_limiter):
        lim.hits.clear()
    yield


@pytest.fixture(autouse=True)
def no_photo_lookups(monkeypatch):
    """Tests never reach Wikipedia; tests of the lookup itself patch httpx instead."""
    from app.services import species_images
    monkeypatch.setattr(species_images, "lookup", lambda sci, timeout=4.0: None)


class Client(TestClient):
    """Test client that sends the CSRF token like the real forms do."""

    def csrf(self) -> str:
        if "av_csrf" not in self.cookies:
            self.get("/login")
        return self.cookies.get("av_csrf")

    def post_form(self, url, data=None, files=None, **kw):
        data = dict(data or {})
        data.setdefault("csrf", self.csrf())
        return self.post(url, data=data, files=files, follow_redirects=kw.pop("follow_redirects", False), **kw)


@pytest.fixture
def client():
    return Client(app)


def signup(c: Client, email="owner@example.com", company="Sierra Tours", name="Ana Guide", password="correct horse 1",
           activity="multi"):
    r = c.post_form("/signup", {"company": company, "name": name, "email": email, "password": password, "agree": "1",
                                "activity": activity})
    assert r.status_code == 303, r.text
    return r


@pytest.fixture
def owner(client):
    signup(client)
    return client


def new_trip(c: Client) -> str:
    r = c.post_form("/app/trips")
    assert r.status_code == 303
    return re.search(r"/app/trips/([0-9a-f]+)", r.headers["location"]).group(1)


def add_day(c: Client, trip_id: str) -> str:
    r = c.post_form(f"/app/trips/{trip_id}/days")
    assert r.status_code == 303
    return re.search(r"day=([0-9a-f]+)", r.headers["location"]).group(1)
