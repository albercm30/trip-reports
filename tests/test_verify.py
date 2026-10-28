import json
from types import SimpleNamespace as S

import httpx

from app.config import settings
from app.services import ai, evalcases, species as sp, verify

from .conftest import add_day, new_trip, signup

CETACEANS = ("Salida de mañana, mar en calma. unos veinte calderones tropicales cerca del puerto, delfines mulares "
             "por ocho! tortuga boba!, muchas pardelas cenicientas, posible zifio? no vimos cachalotes hoy, "
             "ni rastro de las orcas")


def test_free_parser_passes_every_tally_case():
    for c in evalcases.CASES:
        if not c["tally"]:
            continue
        r = evalcases.score(c, sp.parse_tally(c["tally"], sp.default_vocab(), c["lang"]))
        assert r["ok"], (c["id"], r["problems"])


def test_code_checks_fix_what_the_ai_got_wrong():
    ai_rows = [
        {"name": "Calderón tropical", "sci": "Globicephala macrorhynchus", "count": 25, "source": "unos veinte calderones tropicales"},
        {"name": "Delfín mular", "sci": "Tursiops truncatus", "count": 8, "source": "delfines mulares por ocho"},
        {"name": "Pardela cenicienta", "sci": "Calonectris borealis", "count": 30, "source": "muchas pardelas cenicientas"},
        {"name": "Zifio de Cuvier", "sci": "Ziphius cavirostris", "count": None, "source": "posible zifio", "sure": True},
        {"name": "Cachalote", "sci": "Physeter macrocephalus", "count": None, "source": "cachalotes"},
        {"name": "Orca", "sci": "Orcinus orca", "count": None, "source": "orcas"},
    ]
    rows = sp.clean_ai_rows(ai_rows, CETACEANS)
    rows, changes = verify.check_species_rows(rows, CETACEANS, lang="es", tally=CETACEANS)
    got = {r["sci"]: r for r in rows}
    assert got["Globicephala macrorhynchus"]["count"] == 20          # the guide said about twenty
    assert got["Tursiops truncatus"]["star"]                          # "!" right after
    assert got["Calonectris borealis"]["count"] is None               # "muchas" is not 30
    assert got["Ziphius cavirostris"]["sure"] is False                # "posible ... ?"
    assert "Physeter macrocephalus" not in got and "Orcinus orca" not in got  # not seen
    assert "Caretta caretta" in got                                   # missed by the AI, added back
    assert changes


def test_text_checks_catch_invented_facts():
    sp_ = [S(name="Calderón tropical", sci="Globicephala macrorhynchus", count=20, sure=True),
           S(name="Zifio de Cuvier", sci="Ziphius cavirostris", count=None, sure=False)]
    notes = "unos veinte calderones tropicales, posible zifio, no vimos cachalotes"
    bad = ("Salimos temprano y enseguida unos veinte calderones tropicales se acercaron, con dos crías. "
           "Después apareció un zifio de Cuvier y un cachalote enorme saltó junto al barco.")
    kinds = {(p["kind"], p["what"]) for p in verify.check_text(bad, lang="es", species=sp_, notes=notes)}
    assert ("number", "2") in kinds and ("species", "Cachalote") in kinds and ("certainty", "Zifio de Cuvier") in kinds
    good = ("Salimos temprano y enseguida unos veinte calderones tropicales se acercaron al barco. Más tarde vimos lo "
            "que probablemente era un zifio de Cuvier. Esta vez no hubo suerte con los cachalotes.")
    assert verify.check_text(good, lang="es", species=sp_, notes=notes) == []
    english = "We left early and soon about twenty short-finned pilot whales came close to the boat, which was lovely."
    assert {"kind": "language", "what": "English"} in verify.check_text(english, lang="es", species=sp_, notes=notes)


def test_day_draft_is_rewritten_when_the_check_finds_problems(owner, monkeypatch):
    monkeypatch.setattr(settings, "llm_api_key", "gsk_test")
    calls = []

    def fake_draft_day(**kw):
        calls.append(kw)
        if not kw.get("problems"):
            return "We saw a sperm whale and twelve dolphins.", 10, 10
        return "We had a quiet morning at sea.", 10, 10
    monkeypatch.setattr(ai, "draft_day", fake_draft_day)
    tid = new_trip(owner)
    did = add_day(owner, tid)
    owner.post_form(f"/app/trips/{tid}/days/{did}/draft", {"place": "", "notes": "quiet morning, nothing much"})
    assert len(calls) == 2
    assert "Sperm Whale" in calls[1]["problems"] and "12" in calls[1]["problems"]
    page = owner.get(f"/app/trips/{tid}?tab=days&day={did}").text
    assert "We had a quiet morning at sea." in page and "Check before approving" not in page


def test_accuracy_page_runs_a_case(client, monkeypatch):
    monkeypatch.setattr(settings, "admin_emails", ("owner@example.com",))
    monkeypatch.setattr(settings, "llm_api_key", "gsk_test")
    monkeypatch.setattr(settings, "llm_base_url", "https://api.groq.com/openai/v1")
    monkeypatch.setattr(ai, "_gone", set())
    answer = {"species": [{"name": "Lince ibérico", "sci": "Lynx pardinus", "count": 1, "sure": True, "source": "links x1"}]}

    def fake_post(url, json=None, headers=None, timeout=None):
        return httpx.Response(200, json={"choices": [{"message": {"content": __import__("json").dumps(answer)}}]})
    monkeypatch.setattr(ai.httpx, "post", fake_post)
    signup(client)
    assert "Run all tests" in client.get("/app/admin/accuracy").text
    r = client.post("/app/admin/accuracy/birding-andujar", headers={"X-CSRF-Token": client.csrf(), "X-Requested-With": "fetch"})
    j = r.json()
    assert r.status_code == 200 and j["ai_raw"]["found"] == 1
    assert j["ai"]["found"] >= 5  # the code checks add back what the AI missed from the tally


def test_problems_show_on_the_day_and_in_report_checks(owner):
    tid = new_trip(owner)
    did = add_day(owner, tid)
    owner.post_form(f"/app/trips/{tid}/days/{did}", {"place": "", "notes": "quiet morning",
                                                     "narrative": "We had a quiet morning and saw a sperm whale."})
    assert "Mentions Sperm Whale" in owner.get(f"/app/trips/{tid}?tab=days&day={did}").text
    assert "thing(s) in the text to check" in owner.get(f"/app/trips/{tid}?tab=report").text
