from datetime import datetime, timedelta, timezone

from app.db import SessionLocal
from app.models import Organization, PasswordReset, User
from app.security import hash_password, verify_password

from .conftest import Client, signup


def test_password_hashing():
    h = hash_password("a long password")
    assert verify_password("a long password", h)
    assert not verify_password("wrong password", h)
    assert not verify_password("x", "garbage")


def test_signup_creates_org_with_trial(client):
    signup(client)
    with SessionLocal() as db:
        u = db.query(User).one()
        assert u.role == "owner" and u.email == "owner@example.com"
        org = db.get(Organization, u.org_id)
        assert org.plan == "trial" and org.trial_ends_at is not None
    r = client.get("/app?welcome=1")
    assert r.status_code == 200 and "Welcome, Ana" in r.text


def test_signup_validation(client):
    r = client.post_form("/signup", {"company": "X", "name": "Y", "email": "bad", "password": "short", "agree": "1"})
    assert r.status_code == 400
    signup(client)
    other = Client(client.app)
    r = other.post_form("/signup", {"company": "X", "name": "Y", "email": "OWNER@example.com",
                                    "password": "another long pw", "agree": "1"})
    assert r.status_code == 400 and "already" in r.text


def test_csrf_required(client):
    r = client.post("/signup", data={"company": "X"}, follow_redirects=False)
    assert r.status_code == 403


def test_login_logout_and_protection(client):
    signup(client)
    assert client.get("/app").status_code == 200
    client.post_form("/logout")
    r = client.get("/app", follow_redirects=False)
    assert r.status_code == 303 and r.headers["location"].startswith("/login")
    r = client.post_form("/login", {"email": "owner@example.com", "password": "nope nope nope"})
    assert r.status_code == 400
    r = client.post_form("/login", {"email": "Owner@Example.com", "password": "correct horse 1", "next": "/app/insights"})
    assert r.status_code == 303 and r.headers["location"] == "/app/insights"


def test_open_redirect_blocked(client):
    signup(client)
    client.post_form("/logout")
    r = client.post_form("/login", {"email": "owner@example.com", "password": "correct horse 1", "next": "//evil.com"})
    assert r.headers["location"] == "/app"


def test_login_rate_limit(client):
    signup(client)
    client.post_form("/logout")
    for _ in range(10):
        client.post_form("/login", {"email": "owner@example.com", "password": "wrong password!"})
    r = client.post_form("/login", {"email": "owner@example.com", "password": "correct horse 1"})
    assert r.status_code == 429


def test_password_reset_flow(client):
    signup(client)
    client.post_form("/logout")
    r = client.post_form("/forgot", {"email": "owner@example.com"})
    assert r.status_code == 200
    import re
    link = re.search(r"/reset/([\w-]+)", r.text).group(1)  # shown in development without SMTP
    r = client.post_form(f"/reset/{link}", {"password": "brand new password"})
    assert r.status_code == 303
    client.post_form("/logout")
    r = client.post_form("/login", {"email": "owner@example.com", "password": "brand new password"})
    assert r.status_code == 303
    # used links stop working
    assert "expired" in client.get(f"/reset/{link}").text


def test_expired_reset(client):
    signup(client)
    from app.security import sha256
    with SessionLocal() as db:
        u = db.query(User).one()
        db.add(PasswordReset(token_hash=sha256("tok123"), user_id=u.id,
                             expires_at=datetime.now(timezone.utc) - timedelta(minutes=1)))
        db.commit()
    r = client.post_form("/reset/tok123", {"password": "brand new password"})
    assert r.status_code == 400


def test_invite_and_team_isolation(client):
    signup(client)
    r = client.post_form("/app/team/invite", {"email": "guide@example.com"})
    assert r.status_code == 303
    page = client.get("/app/team").text
    import re
    token = re.search(r"/invite/([\w-]+)", page).group(1)
    guide = Client(client.app)
    r = guide.post_form(f"/invite/{token}", {"name": "Gus", "email": "guide@example.com", "password": "guide password 1"})
    assert r.status_code == 303
    assert guide.get("/app").status_code == 200
    # guides can't change company settings or billing
    r = guide.post_form("/app/settings", {"name": "Hacked"})
    assert r.status_code == 303 and r.headers["location"] == "/app"
    # second use of the invite fails
    third = Client(client.app)
    r = third.post_form(f"/invite/{token}", {"name": "X", "email": "x@example.com", "password": "another password"})
    assert r.status_code == 400
    # seat limit (trial = 2 seats) blocks a further invite
    r = client.post_form("/app/team/invite", {"email": ""})
    assert r.status_code == 303
    assert "no free seats" in client.get("/app/team").text


def test_other_org_cannot_see_trip(client):
    signup(client)
    from .conftest import new_trip
    tid = new_trip(client)
    other = Client(client.app)
    signup(other, email="b@example.com", company="Other Co")
    assert other.get(f"/app/trips/{tid}").status_code == 404
    r = other.post_form(f"/app/trips/{tid}", {"title": "pwned"})
    assert r.status_code == 404
