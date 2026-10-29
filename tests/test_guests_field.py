"""Guests' QR page (emails, review links, photos), voice notes and GPS positions."""
import io
import re
from datetime import date

import httpx
import pytest
from PIL import Image

from app.config import settings
from app.db import SessionLocal
from app.models import Day, Guest, GuestPhoto, Organization, Point, Trip
from app.services import guests as gs
from app.services import mail, voice
from tests.conftest import Client, add_day, new_trip, signup


def png() -> bytes:
    b = io.BytesIO()
    Image.new("RGB", (40, 30), (20, 90, 120)).save(b, "PNG")
    return b.getvalue()


def guest_token(c, trip_id) -> str:
    html = c.get(f"/app/trips/{trip_id}?tab=report").text
    return re.search(r"/g/([\w-]+)", html).group(1)


@pytest.fixture
def sent(monkeypatch):
    out = []
    monkeypatch.setattr(settings, "brevo_api_key", "x")
    monkeypatch.setattr(settings, "mail_from", "hola@example.com")
    monkeypatch.setattr(type(settings), "mail_enabled", property(lambda s: True), raising=False)

    def fake(to, subject, body, html=None, sender_name=None, reply_to=None):
        out.append({"to": to, "subject": subject, "body": body, "html": html, "from": sender_name, "reply_to": reply_to})
        return True
    monkeypatch.setattr(mail, "send", fake)
    return out


def setup_trip(owner):
    tid = new_trip(owner)
    owner.post_form(f"/app/trips/{tid}", {"title": "Avistamiento de cetáceos", "lang": "es"})
    did = add_day(owner, tid)
    owner.post_form("/app/settings", {"name": "Ocean Tours", "accent": "#1f5f7a", "report_lang": "es",
                                      "review_google": "g.page/r/abc/review", "review_tripadvisor": "https://www.tripadvisor.es/x"})
    return tid, did


def test_guest_signs_up_and_gets_report_with_review_links(owner, sent):
    tid, _ = setup_trip(owner)
    tok = guest_token(owner, tid)
    guest = Client(owner.app)
    page = guest.get(f"/g/{tok}")
    assert page.status_code == 200 and "Recibe el informe de tu salida" in page.text and "Ocean Tours" in page.text
    r = guest.post_form(f"/g/{tok}", {"email": " Ana@Example.com ", "name": "Ana López", "news": "1"})
    assert r.status_code == 303 and "ok=1" in r.headers["location"]
    assert guest.post_form(f"/g/{tok}", {"email": "no-es-email"}).headers["location"].endswith("err=email")
    assert guest.post_form(f"/g/{tok}", {"email": "bot@example.com", "website": "spam"}).status_code == 303
    with SessionLocal() as db:
        gl = db.query(Guest).all()
        assert [(g.email, g.name, g.news) for g in gl] == [("ana@example.com", "Ana López", True)]
    assert not sent
    r = owner.post_form(f"/app/trips/{tid}/guests/send")
    assert r.status_code == 303
    assert len(sent) == 1
    m = sent[0]
    assert m["to"] == "ana@example.com" and m["from"] == "Ocean Tours" and m["reply_to"] == "owner@example.com"
    assert "Hola Ana" in m["body"] and "/r/" in m["body"] and "https://g.page/r/abc/review" in m["html"]
    assert "Reseña en TripAdvisor" in m["html"]
    # a late guest gets it straight away; the first one isn't emailed twice
    r = guest.post_form(f"/g/{tok}", {"email": "late@example.com"})
    assert "ok=2" in r.headers["location"]
    assert [x["to"] for x in sent] == ["ana@example.com", "late@example.com"]
    report = owner.get(f"/app/trips/{tid}?tab=report").text
    assert "late@example.com" in report and "Reseña en Google" in report
    csv = owner.get(f"/app/trips/{tid}/guests.csv").text
    assert "ana@example.com,Ana López,1" in csv


def test_closed_page_and_boat_card(owner, sent):
    tid, _ = setup_trip(owner)
    tok = guest_token(owner, tid)
    owner.post_form(f"/app/trips/{tid}/guests/toggle")
    guest = Client(owner.app)
    assert "Esta página está cerrada" in guest.get(f"/g/{tok}").text
    guest.post_form(f"/g/{tok}", {"email": "x@example.com"})
    with SessionLocal() as db:
        assert db.query(Guest).count() == 0
    owner.post_form(f"/app/trips/{tid}/guests/toggle")
    card = owner.get("/app/qr-card").text
    assert "<svg" in card
    ctok = re.search(r"/q/([\w-]+)", card).group(1)
    r = guest.get(f"/q/{ctok}", follow_redirects=False)
    assert r.status_code == 302 and r.headers["location"] == f"/g/{tok}"
    with SessionLocal() as db:
        db.get(Trip, tid).start_date = date(2020, 1, 1)
        db.commit()
    assert "no hay ninguna salida abierta" in guest.get(f"/q/{ctok}").text


def test_guest_photos_need_approval(owner):
    tid, _ = setup_trip(owner)
    tok = guest_token(owner, tid)
    guest = Client(owner.app)
    r = guest.post_form(f"/g/{tok}/photos", {"author": "Ana"}, files=[("files", ("a.png", png(), "image/png")),
                                                                     ("files", ("b.txt", b"nope", "text/plain"))])
    assert "ph=1" in r.headers["location"]
    with SessionLocal() as db:
        p = db.query(GuestPhoto).one()
        key, pid = p.storage_key, p.id
        assert not p.approved and p.author == "Ana"
    owner.post_form(f"/app/trips/{tid}/share")
    with SessionLocal() as db:
        share = db.get(Trip, tid).share_token
    assert key not in guest.get(f"/r/{share}").text
    assert guest.get(f"/media/{key}?s={share}").status_code == 404
    owner.post_form(f"/app/trips/{tid}/guest-photos/{pid}/show")
    page = guest.get(f"/r/{share}").text
    assert key in page and "Fotos del grupo" in page and "Foto: Ana" in page
    assert guest.get(f"/media/{key}?s={share}").status_code == 200
    owner.post_form(f"/app/trips/{tid}/guest-photos/{pid}/delete")
    with SessionLocal() as db:
        assert db.query(GuestPhoto).count() == 0


def test_points_and_map(owner):
    tid, did = setup_trip(owner)
    url = f"/app/trips/{tid}/days/{did}/points"
    h = {"X-CSRF-Token": owner.csrf(), "X-Requested-With": "fetch"}
    r = owner.post(url, json={"id": "abc1", "lat": 28.65211, "lon": -17.98532, "acc": 9, "label": "Calderón tropical",
                              "at": "2026-07-04T10:36:00"}, headers=h)
    assert r.status_code == 200 and r.json()["point"]["label"] == "Calderón tropical"
    owner.post(url, json={"id": "abc1", "lat": 28.65211, "lon": -17.98532}, headers=h)  # an offline retry
    assert owner.post(url, json={"lat": 200, "lon": 0}, headers=h).status_code == 400
    with SessionLocal() as db:
        pts = db.query(Point).all()
        assert len(pts) == 1 and pts[0].at.strftime("%H:%M") == "10:36"
    report = owner.get(f"/app/trips/{tid}?tab=report").text
    assert 'class="r-map"' in report and "28.6521" in report and "Dónde los vimos" in report
    owner.post_form(f"/app/trips/{tid}/map")
    assert 'class="r-map"' not in owner.get(f"/app/trips/{tid}?tab=report").text
    days = owner.get(f"/app/trips/{tid}?tab=days").text
    assert "Calderón tropical" in days and "pt_" in days


def test_field_point_without_outing(client):
    signup(client, activity="single")
    h = {"X-CSRF-Token": client.csrf(), "X-Requested-With": "fetch"}
    r = client.post("/app/field/points", json={"lat": 28.6, "lon": -17.9, "at": "2026-07-04T10:00:00"}, headers=h)
    assert r.status_code == 200
    with SessionLocal() as db:
        d = db.get(Day, r.json()["day"])
        assert d.date == date(2026, 7, 4) and len(d.points) == 1
    r2 = client.post("/app/field/points", json={"lat": 28.61, "lon": -17.9, "at": "2026-07-04T11:00:00"}, headers=h)
    assert r2.json()["day"] == r.json()["day"]  # same date, same outing


def test_field_point_multi_day_is_not_guessed(owner):
    h = {"X-CSRF-Token": owner.csrf(), "X-Requested-With": "fetch"}
    r = owner.post("/app/field/points", json={"lat": 28.6, "lon": -17.9, "at": "2026-07-04T10:00:00"}, headers=h)
    assert r.status_code == 409 and r.json()["error"] == "no_day"


def test_voice_note_appends_text(owner, monkeypatch):
    tid, did = setup_trip(owner)
    seen = {}

    def fake(audio, mime, lang, words):
        seen.update(mime=mime, lang=lang)
        return "grupo de calderones con crías"
    monkeypatch.setattr(voice, "transcribe", fake)
    h = {"X-CSRF-Token": owner.csrf(), "X-Requested-With": "fetch"}
    files = {"audio": ("note.webm", b"\x1aE\xdf\xa3fake", "audio/webm")}
    r = owner.post(f"/app/trips/{tid}/days/{did}/voice", data={"lang": "es", "append": "1"}, files=files, headers=h)
    assert r.json() == {"ok": True, "text": "grupo de calderones con crías"}
    assert seen == {"mime": "audio/webm", "lang": "es"}
    with SessionLocal() as db:
        assert db.get(Day, did).notes == "grupo de calderones con crías"
    r = owner.post(f"/app/trips/{tid}/days/{did}/voice", data={"append": "0"}, files=files, headers=h)
    with SessionLocal() as db:
        assert db.get(Day, did).notes == "grupo de calderones con crías"  # the open page inserts it itself

    def down(*a, **k):
        raise voice.VoiceError("unavailable")
    monkeypatch.setattr(voice, "transcribe", down)
    r = owner.post(f"/app/trips/{tid}/days/{did}/voice", data={"append": "1"}, files=files, headers=h)
    assert r.status_code == 503  # the phone keeps it and tries again later


def test_whisper_request(monkeypatch):
    monkeypatch.setattr(settings, "llm_api_key", "k")
    monkeypatch.setattr(settings, "llm_base_url", "https://api.groq.com/openai/v1")
    calls = []

    class R:
        status_code = 200

        def json(self):
            return {"text": " Calderones tropicales, unos veinte. "}

    def post(url, **kw):
        calls.append((url, kw))
        return R()
    monkeypatch.setattr(voice.httpx, "post", post)
    out = voice.transcribe(b"abc", "audio/mp4", "es", ["Calderón tropical", "calderón tropical", "Pardela cenicienta"])
    assert out == "Calderones tropicales, unos veinte."
    url, kw = calls[0]
    assert url.endswith("/audio/transcriptions") and kw["data"]["model"] == "whisper-large-v3-turbo"
    assert kw["data"]["language"] == "es" and kw["data"]["prompt"] == "Calderón tropical, Pardela cenicienta"
    assert kw["files"]["file"][0] == "note.m4a"
    assert voice.tidy("Subtítulos realizados por la comunidad de Amara.org") == ""


def test_example_report_has_map():
    from app.services.demo_marine import build_marine_trip
    from app.services.reportdata import build_report
    R = build_report(build_marine_trip("es"), None, "X")
    assert [p["n"] for p in R["points"]] == [1, 2, 3, 4] and R["points"][0]["time"] == "10:36"


def test_offline_page_and_service_worker(client):
    page = client.get("/offline", headers={"Accept-Language": "es"}).text
    assert "Grabar nota de voz" in page and "field.js" in page
    sw = client.get("/sw.js").text
    assert '"/offline"' in sw and "caches.match(\"/offline\")" in sw


def test_clean_url_and_email():
    assert gs.clean_url("g.page/r/x/review") == "https://g.page/r/x/review"
    assert gs.clean_url("javascript:alert(1)") == ""
    assert gs.clean_email("A@B.co") == "a@b.co" and gs.clean_email("a@b") is None
