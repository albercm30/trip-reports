import io

import pytest
from datetime import date, datetime, timedelta, timezone

from PIL import Image

from app.db import SessionLocal
from app.models import Day, Organization, Photo, Sighting, Trip
from app.services import ai, drafting, taxonomy

from .conftest import Client, add_day, new_trip, signup


def _day(day_id):
    with SessionLocal() as db:
        d = db.get(Day, day_id)
        _ = list(d.sightings), list(d.photos)
        return d


def test_trip_edit_autosave_and_dates(owner):
    tid = new_trip(owner)
    d1 = add_day(owner, tid)
    d2 = add_day(owner, tid)
    r = owner.post_form(f"/app/trips/{tid}", {"title": "Lynx Weekend", "location": "Andújar", "start_date": "2026-03-01",
                                               "guests": "6", "guides": "Ana"},
                        headers={"X-Requested-With": "fetch", "X-CSRF-Token": owner.csrf()})
    assert r.status_code == 200 and r.json()["ok"]
    with SessionLocal() as db:
        t = db.get(Trip, tid)
        assert t.title == "Lynx Weekend" and t.guests == 6
        assert [d.date for d in t.days] == [date(2026, 3, 1), date(2026, 3, 2)]
    assert d1 != d2


def test_free_species_parse_and_edit(owner):
    tid = new_trip(owner)
    did = add_day(owner, tid)
    r = owner.post_form(f"/app/trips/{tid}/days/{did}/species/parse",
                        {"place": "Dam", "notes": "", "narrative": "", "raw_tally": "40 griffon vultures, lynx x1!, heard eagle owl, warbler?"})
    assert r.status_code == 303
    d = _day(did)
    names = {s.name: s for s in d.sightings}
    assert names["Griffon Vulture"].count == 40 and names["Griffon Vulture"].source == "40 griffon vultures"
    assert names["Iberian Lynx"].star and names["Iberian Lynx"].count == 1
    assert names["Eurasian Eagle-Owl"].heard
    assert not names["Warbler"].sure
    assert d.raw_tally == ""
    page = owner.get(f"/app/trips/{tid}?tab=days&day={did}").text
    assert "From your words:" in page
    # edit a row through the day form, untick "confirmed" on the lynx
    lynx = names["Iberian Lynx"]
    form = {"place": "Dam", "notes": "", "narrative": "", "raw_tally": ""}
    for s in d.sightings:
        form.update({f"sp_{s.id}_name": s.name, f"sp_{s.id}_sci": s.sci, f"sp_{s.id}_count": s.count or "",
                     f"sp_{s.id}_sure": "1" if s.sure else ""})
    form[f"sp_{lynx.id}_sure"] = ""
    form[f"sp_{lynx.id}_name"] = "Iberian Lynx"
    owner.post_form(f"/app/trips/{tid}/days/{did}", form)
    d = _day(did)
    lynx = next(s for s in d.sightings if s.id == lynx.id)
    assert lynx.name == "Iberian Lynx" and not lynx.sure and not lynx.star  # unchecked boxes = false


def test_free_day_draft_uses_only_given_facts(owner):
    tid = new_trip(owner)
    did = add_day(owner, tid)
    owner.post_form(f"/app/trips/{tid}/days/{did}/species/parse",
                    {"place": "Encinarejo dam", "notes": "Cold clear morning. Lynx on far bank ~300m!!", "narrative": "",
                     "raw_tally": "lynx x1!, bonelli's eagle?"})
    r = owner.post_form(f"/app/trips/{tid}/days/{did}/draft",
                        {"place": "Encinarejo dam", "notes": "Cold clear morning. Lynx on far bank ~300m!!", "narrative": ""})
    assert r.status_code == 303
    d = _day(did)
    assert "Encinarejo dam" in d.narrative and "about 300 m" in d.narrative
    assert "possible bonelli's eagle" in d.narrative.lower()
    assert not d.approved


def test_approve_requires_text(owner):
    tid = new_trip(owner)
    did = add_day(owner, tid)
    owner.post_form(f"/app/trips/{tid}/days/{did}", {"place": "x", "notes": "", "narrative": "", "approved": "1"})
    assert not _day(did).approved
    owner.post_form(f"/app/trips/{tid}/days/{did}", {"place": "x", "notes": "", "narrative": "We saw things.", "approved": "1"})
    d = _day(did)
    assert d.approved and d.approved_by == "Ana Guide"


def test_ai_path_used_when_configured(owner, monkeypatch):
    monkeypatch.setattr(drafting.settings, "anthropic_api_key", "sk-test")
    seen = {}

    def fake_parse(tally, notes, lang, ctx, known=""):
        seen.update(tally=tally, notes=notes)
        return ({"species": [
            {"name": "Iberian Lynx", "sci": "Lynx pardinus", "count": 1, "heard": False, "sure": True, "star": True,
             "group": "mammals", "source": "lynx!"},
            {"name": "Eagle", "sci": "", "count": None, "sure": False, "group": "birds", "source": "eagle"},
            {"name": "Griffon Vulture", "sci": "Gyps fulvus", "count": 30, "group": "birds", "source": "30 grifons"},
            {"name": "Golden Eagle", "sci": "Aquila chrysaetos", "source": "golden eagle on the ridge"},
            {"bad": "row"}]}, 120, 80)
    monkeypatch.setattr(ai, "parse_species", fake_parse)
    monkeypatch.setattr(ai, "draft_day", lambda **kw: ("We watched an Iberian lynx.", 300, 60))
    tid = new_trip(owner)
    did = add_day(owner, tid)
    owner.post_form(f"/app/trips/{tid}/days/{did}/species/parse",
                    {"place": "", "notes": "Morning at the dam, 30 grifons over the ridge", "narrative": "", "raw_tally": "lynx!, eagle"})
    assert seen["notes"].startswith("Morning at the dam")  # notes are read too
    owner.post_form(f"/app/trips/{tid}/days/{did}/draft", {"place": "", "notes": "lynx", "narrative": ""})
    d = _day(did)
    # the golden eagle was never written by the guide, so it is dropped
    assert [s.name for s in d.sightings] == ["Iberian Lynx", "Eagle", "Griffon Vulture"]
    assert d.sightings[0].group == "Mammals"
    assert d.narrative == "We watched an Iberian lynx."
    from app.models import AIUsage
    with SessionLocal() as db:
        assert db.query(AIUsage).count() == 2


def test_openai_compatible_provider_and_proofread(owner, monkeypatch):
    import httpx
    from app.services import ai as ai_mod
    monkeypatch.setattr(drafting.settings, "llm_api_key", "gsk-test")
    calls = []

    class R:
        def __init__(self, content, status=200):
            self.status_code, self._c, self.text = status, content, ""

        def json(self):
            return {"choices": [{"message": {"content": self._c}}], "usage": {"prompt_tokens": 10, "completion_tokens": 5}}

    def fake_post(url, json=None, headers=None, timeout=None):
        calls.append((url, json, headers))
        prompt = json["messages"][1]["content"]
        if prompt.startswith("Correct the spelling"):
            return R("We saw a griffon vulture and a beautiful Iberian lynx at the dam.")
        return R('{"species":[{"name":"Griffon Vulture","sci":"Gyps fulvus","count":40,"source":"fourty grifons"}]}')
    monkeypatch.setattr(httpx, "post", fake_post)
    tid = new_trip(owner)
    did = add_day(owner, tid)
    owner.post_form(f"/app/trips/{tid}/days/{did}/species/parse", {"place": "", "notes": "", "narrative": "",
                                                                     "raw_tally": "fourty grifons"})
    assert calls[0][0] == "https://api.groq.com/openai/v1/chat/completions"
    assert calls[0][2]["Authorization"] == "Bearer gsk-test" and calls[0][1]["response_format"]["type"] == "json_object"
    assert _day(did).sightings[0].name == "Griffon Vulture"
    r = owner.post_form(f"/app/trips/{tid}/days/{did}/proofread",
                        {"place": "", "notes": "", "narrative": "We saw a grifon vulture and a beatiful iberian links at the dam."})
    assert r.status_code == 303
    assert _day(did).narrative == "We saw a griffon vulture and a beautiful Iberian lynx at the dam."
    # a "proofread" that rewrites the whole thing is refused
    monkeypatch.setattr(httpx, "post", lambda *a, **k: R("Completely different and much much longer text " * 10))
    with pytest.raises(ai_mod.AIError):
        ai_mod.proofread("Short note.", "en")


def test_ai_failure_falls_back_to_free(owner, monkeypatch):
    monkeypatch.setattr(drafting.settings, "anthropic_api_key", "sk-test")

    def boom(**kw):
        raise ai.AIError("rate_limited")
    monkeypatch.setattr(ai, "draft_day", boom)
    tid = new_trip(owner)
    did = add_day(owner, tid)
    r = owner.post_form(f"/app/trips/{tid}/days/{did}/draft", {"place": "Dam", "notes": "Great morning", "narrative": ""})
    assert r.status_code == 303
    assert "Great morning" in _day(did).narrative


def test_taxonomy_marks_unknown_names(monkeypatch):
    monkeypatch.setattr(taxonomy.settings, "gbif_check", True)
    monkeypatch.setattr(taxonomy, "match_scientific", lambda sci: {"key": 1, "canonical": "Lynx pardinus", "class": "Mammalia"} if sci == "Lynx pardinus" else None)
    monkeypatch.setattr(taxonomy, "match_common", lambda name: {"key": 2, "canonical": "Gyps fulvus", "class": "Aves"} if name == "Griffon vulture" else None)
    rows = taxonomy.check_rows([
        {"name": "Lynx", "sci": "Lynx pardinus", "sure": True},
        {"name": "Fake", "sci": "Fakeus inventus", "sure": True},
        {"name": "Griffon vulture", "sci": "", "sure": True},
        {"name": "Warbler", "sci": "", "sure": False},
    ])
    assert rows[0]["taxon_status"] == "matched"
    assert rows[1]["taxon_status"] == "unmatched" and rows[1]["sure"] is False
    assert rows[2]["sci"] == "Gyps fulvus" and rows[2]["taxon_status"] == "matched"
    assert rows[3]["taxon_status"] == "unchecked"


def test_photos_upload_strip_and_access(owner):
    tid = new_trip(owner)
    did = add_day(owner, tid)
    buf = io.BytesIO()
    img = Image.new("RGB", (3000, 2000), (40, 120, 90))
    exif = Image.Exif()
    exif[0x8825] = {1: "N", 2: (37.0, 1.0, 1.0)}  # GPS IFD
    img.save(buf, "JPEG", exif=exif)
    r = owner.post_form(f"/app/trips/{tid}/days/{did}/photos",
                        files=[("files", ("a.jpg", buf.getvalue(), "image/jpeg")), ("files", ("b.txt", b"not an image", "text/plain"))])
    assert r.status_code == 303
    d = _day(did)
    assert len(d.photos) == 1
    p = d.photos[0]
    assert max(p.width, p.height) == 1800
    data = owner.get(f"/media/{p.storage_key}").content
    assert not Image.open(io.BytesIO(data)).getexif()  # metadata removed
    stranger = Client(owner.app)
    assert stranger.get(f"/media/{p.storage_key}").status_code == 404
    # shared report gives guests access to that trip's photos only
    owner.post_form(f"/app/trips/{tid}/share")
    with SessionLocal() as db:
        tok = db.get(Trip, tid).share_token
    assert stranger.get(f"/media/{p.storage_key}?s={tok}").status_code == 200
    other = Client(owner.app)
    signup(other, email="z@example.com", company="Z")
    t2 = new_trip(other)
    other.post_form(f"/app/trips/{t2}/share")
    with SessionLocal() as db:
        tok2 = db.get(Trip, t2).share_token
    assert stranger.get(f"/media/{p.storage_key}?s={tok2}").status_code == 404
    # delete photo removes the file
    owner.post_form(f"/app/trips/{tid}/days/{did}/photos/{p.id}/delete", {"place": "", "notes": "", "narrative": ""})
    with SessionLocal() as db:
        assert db.query(Photo).count() == 0
    assert owner.get(f"/media/{p.storage_key}").status_code == 404


def test_report_share_and_unshare(owner):
    owner.post_form("/app/demo/example")
    with SessionLocal() as db:
        t = db.query(Trip).one()
        tid = t.id
    page = owner.get(f"/app/trips/{tid}?tab=report").text
    assert "Iberian Lynx Weekend" in page and "The tally" in page and "Ready to send" in page
    owner.post_form(f"/app/trips/{tid}/share")
    with SessionLocal() as db:
        tok = db.get(Trip, tid).share_token
    guest = Client(owner.app)
    r = guest.get(f"/r/{tok}")
    assert r.status_code == 200 and "Iberian Lynx" in r.text and r.headers["x-robots-tag"].startswith("noindex")
    owner.post_form(f"/app/trips/{tid}/unshare")
    assert guest.get(f"/r/{tok}").status_code == 404


def test_csv_export(owner):
    owner.post_form("/app/demo/example")
    with SessionLocal() as db:
        tid = db.query(Trip).one().id
    r = owner.get(f"/app/trips/{tid}/sightings.csv")
    assert r.status_code == 200 and "Lynx pardinus" in r.text and r.headers["content-type"].startswith("text/csv")


def test_intro_draft_and_delete_trip(owner):
    owner.post_form("/app/demo/example")
    with SessionLocal() as db:
        tid = db.query(Trip).one().id
    r = owner.post_form(f"/app/trips/{tid}/intro/draft", {"title": "Lynx", "location": "Andújar"})
    assert r.status_code == 303
    with SessionLocal() as db:
        t = db.get(Trip, tid)
        assert t.intro.startswith("Lynx: 3 days in Andújar") and "15 species" in t.summary
    owner.post_form(f"/app/trips/{tid}/delete")
    with SessionLocal() as db:
        assert db.query(Trip).count() == 0 and db.query(Sighting).count() == 0


def test_demo_season_and_insights(owner):
    r = owner.post_form("/app/demo/season")
    assert r.status_code == 303
    page = owner.get("/app/insights").text
    assert "Your season in numbers" in page and "How often you find your target species" in page
    assert "recorded on" in page
    r = owner.post("/app/insights/season", headers={"X-Requested-With": "fetch", "X-CSRF-Token": owner.csrf()})
    assert r.status_code == 200 and r.json()["engine"] == "free" and "16 trips" in r.json()["text"]
    owner.post_form("/app/demo/remove")
    with SessionLocal() as db:
        assert db.query(Trip).count() == 0


def test_spanish_ui_and_report(client):
    client.cookies.set("lang", "es")
    signup(client)
    page = client.get("/app").text
    assert "Ejemplo: avistamiento de cetáceos (Canarias)" in page
    client.post_form("/app/demo/example")
    with SessionLocal() as db:
        tid = db.query(Trip).one().id
    page = client.get(f"/app/trips/{tid}?tab=report").text
    assert "El recuento" in page and "Lince ibérico" in page


def test_trial_expiry_makes_read_only(owner):
    tid = new_trip(owner)
    with SessionLocal() as db:
        org = db.query(Organization).one()
        org.trial_ends_at = datetime.now(timezone.utc) - timedelta(days=1)
        db.commit()
    r = owner.post_form(f"/app/trips/{tid}", {"title": "x"})
    assert r.status_code == 303 and r.headers["location"] == "/app/billing"
    assert owner.get(f"/app/trips/{tid}").status_code == 200  # still readable
    assert owner.get("/app/account/export").status_code == 200  # and exportable


def test_export_and_delete_account(owner):
    owner.post_form("/app/demo/example")
    r = owner.get("/app/account/export")
    assert r.status_code == 200 and r.json()["trips"][0]["title"] == "Iberian Lynx Weekend"
    r = owner.post_form("/app/account/delete", {"password": "wrong", "confirm": "DELETE"})
    assert r.status_code == 400
    r = owner.post_form("/app/account/delete", {"password": "correct horse 1", "confirm": "DELETE"})
    assert r.status_code == 303
    with SessionLocal() as db:
        assert db.query(Organization).count() == 0 and db.query(Trip).count() == 0


def test_photos_in_database_storage(owner, monkeypatch):
    from app.services import storage
    monkeypatch.setattr(storage, "_store", storage.DBStorage())
    tid = new_trip(owner)
    did = add_day(owner, tid)
    buf = io.BytesIO()
    Image.new("RGB", (400, 300), (10, 20, 30)).save(buf, "PNG")
    owner.post_form(f"/app/trips/{tid}/days/{did}/photos", files=[("files", ("a.png", buf.getvalue(), "image/png"))])
    p = _day(did).photos[0]
    r = owner.get(f"/media/{p.storage_key}")
    assert r.status_code == 200 and r.content[:2] == b"\xff\xd8"  # stored as JPEG
    owner.post_form(f"/app/trips/{tid}/delete")
    from app.models import Blob
    with SessionLocal() as db:
        assert db.query(Blob).count() == 0


def test_everything_in_spanish(client):
    client.cookies.set("lang", "es")
    page = client.get("/").text
    assert "Informes de Viaje" in page and "Prueba gratis" in page
    signup(client)
    client.post_form("/app/demo/example")
    with SessionLocal() as db:
        t = db.query(Trip).one()
        assert t.location.endswith("España") and t.days[0].place.startswith("Presa del Encinarejo")
        assert t.days[0].notes.startswith("Quedamos")
        tid = t.id
    report = client.get(f"/app/trips/{tid}?tab=report").text
    assert "Informe creado con Informes de Viaje" in report and "Sierra de Andújar, Jaén, España" in report
    days = client.get(f"/app/trips/{tid}?tab=days").text
    assert 'href="/lang/en"' in days  # language switch in the app header


def test_trip_report_language_overrides_company(owner):
    from app.db import SessionLocal
    from app.models import Trip
    tid = new_trip(owner)
    owner.post_form(f"/app/trips/{tid}", {"title": "Calderones", "lang": "es"})
    with SessionLocal() as db:
        t = db.get(Trip, tid)
        assert t.lang == "es" and t.report_lang == "es" and t.org.report_lang == "en"
    page = owner.get(f"/app/trips/{tid}?tab=trip").text
    assert 'value="es" selected' in page
    owner.post_form(f"/app/trips/{tid}", {"title": "Calderones", "lang": ""})
    with SessionLocal() as db:
        assert db.get(Trip, tid).report_lang == "en"


def test_whale_watching_example_and_season(owner):
    from app.db import SessionLocal
    from app.models import Trip
    from app.services import verify
    from app.services.reportdata import build_tally
    owner.post_form("/app/demo/example", {"kind": "marine"})
    r = owner.post_form("/app/demo/season", {"kind": "marine"})
    assert r.status_code == 303
    with SessionLocal() as db:
        trips = db.query(Trip).all()
        ex = [t for t in trips if t.intro]
        assert len(ex) == 1 and "La Palma" in ex[0].location and len(trips) == 91
        t = ex[0]
        assert verify.day_problems(t.days[0], t, 1) == [] and verify.trip_text_problems(t, len(build_tally(t))) == []
    page = owner.get("/app/insights").text
    assert "Short-finned Pilot Whale" in page or "Calderón tropical" in page
    assert "Pilot" in owner.get("/example?kind=marine").text
