import httpx
import pytest

from app.db import SessionLocal
from app.models import SpeciesImage
from app.services import species_images as si
from app.services.reportdata import build_report

SUMMARY = {"title": "Bottlenose dolphin", "originalimage": {
    "source": "https://upload.wikimedia.org/wikipedia/commons/1/10/Tursiops_truncatus_01.jpg"}}


def commons(licence="CC BY-SA 4.0", artist='<a href="//commons.wikimedia.org/wiki/User:Ann">Ann &amp; Bo</a>'):
    return {"query": {"pages": {"1": {"imageinfo": [{
        "thumburl": "https://upload.wikimedia.org/wikipedia/commons/thumb/1/10/Tursiops_truncatus_01.jpg/640px-Tursiops_truncatus_01.jpg",
        "descriptionurl": "https://commons.wikimedia.org/wiki/File:Tursiops_truncatus_01.jpg",
        "extmetadata": {"LicenseShortName": {"value": licence}, "Artist": {"value": artist}}}]}}}}


class Resp:
    def __init__(self, data, status=200):
        self.data, self.status_code = data, status

    def json(self):
        return self.data

    def raise_for_status(self):
        if self.status_code >= 400:
            raise httpx.HTTPStatusError("bad", request=None, response=None)


@pytest.fixture
def real_lookup(monkeypatch):
    import importlib
    fresh = importlib.reload(si)  # undo the autouse stub
    yield fresh


def fake_get(licence="CC BY-SA 4.0", summary=SUMMARY):
    calls = []

    def get(url, **kw):
        calls.append(url)
        if "rest_v1" in url:
            return Resp(summary) if summary else Resp({}, 404)
        return Resp(commons(licence))
    return get, calls


def test_lookup_reads_commons_credit(real_lookup, monkeypatch):
    get, calls = fake_get()
    monkeypatch.setattr(real_lookup.httpx, "get", get)
    r = real_lookup.lookup("Tursiops truncatus")
    assert r["url"].endswith("640px-Tursiops_truncatus_01.jpg")
    assert r["credit"] == "Ann & Bo" and r["license"] == "CC BY-SA 4.0"
    assert "Tursiops_truncatus" in calls[0]


@pytest.mark.parametrize("lic,ok", [("CC BY-SA 4.0", True), ("CC0", True), ("Public domain", True), ("CC BY 2.0", True),
                                    ("CC BY-NC 2.0", False), ("CC BY-ND 3.0", False), ("Fair use", False), ("", False)])
def test_only_free_licences(lic, ok):
    assert si.free_licence(lic) is ok


def test_non_free_photo_is_skipped(real_lookup, monkeypatch):
    get, _ = fake_get("CC BY-NC-SA 2.0")
    monkeypatch.setattr(real_lookup.httpx, "get", get)
    assert real_lookup.lookup("Tursiops truncatus") is None


def test_cache_and_network_errors(real_lookup, monkeypatch):
    get, calls = fake_get()
    monkeypatch.setattr(real_lookup.httpx, "get", get)
    db = SessionLocal()
    out = real_lookup.get(db, ["Tursiops truncatus"])
    assert out["Tursiops truncatus"].credit == "Ann & Bo"
    n = len(calls)
    real_lookup.get(db, ["Tursiops truncatus"])
    assert len(calls) == n  # cached

    def boom(url, **kw):
        raise httpx.ConnectError("offline")
    monkeypatch.setattr(real_lookup.httpx, "get", boom)
    assert real_lookup.get(db, ["Delphinus delphis"]) == {}
    assert db.get(SpeciesImage, "Delphinus delphis") is None  # a failure is not cached as "no photo"
    db.close()


def test_report_uses_photos_only_for_confirmed_species(owner):
    from app.services.demo_marine import build_marine_trip
    trip = build_marine_trip("es")
    scis = [s.sci for s in trip.days[0].sightings]
    imgs = {sci: SpeciesImage(sci=sci, ok=True, url=f"https://x/{i}.jpg", credit="A", license="CC0", page="p")
            for i, sci in enumerate(scis)}
    trip.days[0].sightings[0].sure = False
    R = build_report(trip, None, "X", imgs)
    sure = {s.sci for s in trip.days[0].sightings if s.sure}
    assert scis[0] not in R["pics"] and set(R["pics"]) == sure and len(R["featured"]) == len(sure)
    assert R["t"]["spotlight"] == "Especies del viaje"


def test_photos_switch_off(owner):
    from types import SimpleNamespace
    assert si.for_trip(None, SimpleNamespace(days=[]), SimpleNamespace(species_photos=False)) == {}


def test_example_report_shows_reference_photos(client, monkeypatch):
    def fake(db, trip, org, budget=4.0):
        return {s.sci: SpeciesImage(sci=s.sci, ok=True, url="https://upload.wikimedia.org/x.jpg", credit="Ann",
                                    license="CC BY 4.0", page="https://commons.wikimedia.org/wiki/File:x.jpg")
                for d in trip.days for s in d.sightings}
    monkeypatch.setattr(si, "for_trip", fake)
    html = client.get("/example?kind=marine&rl=es").text
    assert "Especies del viaje" in html and "Créditos de las fotos" in html and "CC BY 4.0" in html
    assert 'class="r-th"' in html
