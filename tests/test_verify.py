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
    good = ("Salimos temprano y enseguida vimos unos veinte calderones tropicales. Más tarde vimos lo "
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
        return "We had a quiet morning.", 10, 10
    monkeypatch.setattr(ai, "draft_day", fake_draft_day)
    monkeypatch.setattr(ai, "unsupported_claims", lambda text, notes, sp_: ([], 0, 0))
    tid = new_trip(owner)
    did = add_day(owner, tid)
    owner.post_form(f"/app/trips/{tid}/days/{did}/draft", {"place": "", "notes": "quiet morning, nothing much"})
    assert len(calls) == 2
    assert "Sperm Whale" in calls[1]["problems"] and "12" in calls[1]["problems"]
    page = owner.get(f"/app/trips/{tid}?tab=days&day={did}").text
    assert "We had a quiet morning." in page and "Check before approving" not in page


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


def test_claim_checker_feeds_the_rewrite(monkeypatch):
    from app.services.drafting import checked_draft
    calls = []

    def write(previous, problems):
        calls.append(problems)
        return "Salimos con mar en calma y vimos calderones." if previous else "Bajo un sol radiante vimos calderones saltando."
    monkeypatch.setattr(ai, "unsupported_claims", lambda text, notes, s: (
        [{"quote": "Bajo un sol radiante", "why": "weather not in notes"}, {"quote": "saltando", "why": "behaviour"}]
        if "sol" in text else [], 0, 0))
    res = checked_draft(write, lambda t: [], "mar en calma, calderones", "- Calderón tropical", "es")
    assert res["result"] == "Salimos con mar en calma y vimos calderones."
    assert "Bajo un sol radiante" in calls[1] and "saltando" in calls[1]


def test_claim_quotes_must_really_be_in_the_text(monkeypatch):
    monkeypatch.setattr(ai, "complete", lambda *a, **k: (
        '{"unsupported": [{"quote": "saltando", "why": "x"}, {"quote": "una ballena azul", "why": "made up"}]}', 0, 0))
    found, _, _ = ai.unsupported_claims("Vimos calderones saltando.", "calderones", "")
    assert [f["quote"] for f in found] == ["saltando"]


def test_tidy_removes_markdown_and_checklists():
    t = "Un gran día.\n\n**Lista de avistamientos del Día 1**\n- Calderón gris – 14\n- Delfín común"
    assert verify.tidy(t) == "Un gran día."


def test_names_without_scientific_name_are_looked_up():
    text = "creo que un delfín listado; varias gaviotas patiamarillas; dos rorcuales tropicales"
    rows = [{"name": "Delfín común", "sci": "Tursiops truncatus", "count": 1, "sure": False, "source": "creo que un delfín listado"},
            {"name": "gaviotas patiamarillas", "sci": "", "count": None, "sure": False, "source": "varias gaviotas patiamarillas"},
            {"name": "Rorcual tropical", "sci": "", "count": 2, "sure": True, "source": "dos rorcuales tropicales"}]
    rows, _ = verify.check_species_rows(sp.clean_ai_rows(rows, text), text, lang="es", tally=text)
    got = {r["sci"]: r for r in rows}
    assert set(got) == {"Stenella coeruleoalba", "Larus michahellis", "Balaenoptera edeni"}
    assert got["Stenella coeruleoalba"]["sure"] is False and got["Larus michahellis"]["sure"] is True


def test_ai_species_mistakes_from_the_live_run_are_corrected():
    """Real mistakes from a run against the live AI (Admin > Test accuracy)."""
    cases = [("errores-dictado", [{"name": "Alcatraz", "sci": "Phalacrocorax carbo", "count": 2, "source": "un par de alcatraces"}]),
             ("dudas-es", [{"name": "Delfín listado", "sci": "Stenella coeruleoalba", "count": 1, "sure": True,
                            "source": "un delfín listado"}])]
    for cid, rows in cases:
        c = evalcases.by_id(cid)
        got, _ = verify.check_species_rows(sp.clean_ai_rows(rows, c["tally"]), c["tally"], lang=c["lang"], tally=c["tally"])
        assert evalcases.score(c, got)["ok"], (cid, evalcases.score(c, got))
    c = evalcases.by_id("birding-andujar")
    got, _ = verify.check_species_rows(sp.clean_ai_rows(
        [{"name": "Imperial Eagle", "sci": "Aquila heliaca", "count": 2, "source": "imperial eagle pair!"}], c["tally"]),
        c["tally"], lang="en", tally=c["tally"])
    assert "Aquila heliaca" not in {r["sci"] for r in got} and "Aquila adalberti" in {r["sci"] for r in got}


def test_checker_false_alarms_on_true_facts_are_ignored():
    sp_ = [S(name="Cinereous Vulture", sci="Aegypius monachus", count=6, sure=True),
           S(name="Delfín moteado del Atlántico", sci="Stenella frontalis", count=4, sure=True)]
    kept = verify.drop_false_claims([{"what": "six Cinereous Vultures"}, {"what": "perched among the cliffs"},
                                     {"what": "cuatro delfines moteados del Atlántico"}], sp_,
                                    "6 black vultures, tres no cuatro delfines moteados", "en")
    assert [k["what"] for k in kept] == ["perched among the cliffs"]


def test_plural_and_short_names_are_recognised_in_text():
    names = [e["en"] for e in verify.mentioned_species("two sperm whales, six cinereous vultures, three hoopoes")]
    assert names == ["Sperm Whale", "Cinereous Vulture", "Eurasian Hoopoe"] or set(names) == {
        "Sperm Whale", "Cinereous Vulture", "Eurasian Hoopoe"}
    assert verify.mentioned_species("un martín pescador común pasó") and not any(
        e["en"] == "Eurasian Crag Martin" for e in verify.mentioned_species("un martín pescador común pasó"))


def test_doubt_does_not_leak_to_the_next_species():
    t = "calderones grises unos doce, perdón, catorce; creo que un delfín listado; varias gaviotas patiamarillas"
    rows = [{"name": "Delfín listado", "sci": "Stenella coeruleoalba", "count": 1, "sure": True, "source": "un delfín listado"},
            {"name": "Gaviota patiamarilla", "sci": "Larus michahellis", "count": None, "sure": True,
             "source": "varias gaviotas patiamarillas"}]
    got = {r["sci"]: r for r in verify.check_species_rows(sp.clean_ai_rows(rows, t), t, lang="es")[0]}
    assert got["Stenella coeruleoalba"]["sure"] is False and got["Larus michahellis"]["sure"] is True


def test_invented_details_heard_and_cut_text_are_caught():
    sp_ = [S(name="Hoopoe", sci="Upupa epops", count=3, sure=True, heard=False),
           S(name="Zifio", sci="", count=None, sure=False, heard=False),
           S(name="Eurasian Eagle-Owl", sci="Bubo bubo", count=None, sure=True, heard=True)]
    p = verify.check_text("We were delighted to spot three hoopoes gliding over the water.", lang="en", species=sp_,
                          notes="3 hoopoes")
    assert {x["what"] for x in p if x["kind"] == "detail"} == {"gliding", "water"}
    p = verify.check_text("Además, escuchamos la posible presencia de un zifio. Luego vimos", lang="es", species=sp_,
                          notes="posible zifio")
    assert {"kind": "heard", "what": "Zifio"} in p and {"kind": "format", "what": "cut"} in p
    assert verify.check_text("The deep call of an Eagle-Owl was a treat.", lang="en", species=sp_,
                             notes="heard eagle owl") == []
    # Spanish notes support an English report: "mar de fondo" -> "sea"
    assert verify.check_text("We went out on a lumpy sea.", lang="en", species=[], notes="mar de fondo") == []


def test_code_alone_reads_every_tally_case_even_if_the_ai_returns_nothing():
    for c in evalcases.CASES:
        if not c["tally"] or c["id"] == "cetaceos-la-palma" and False:
            continue
        t = (c["tally"] + "\n" + c["notes"]).strip()
        rows, _ = verify.check_species_rows([], t, lang=c["lang"], tally=c["tally"])
        assert evalcases.score(c, rows)["ok"], (c["id"], evalcases.score(c, rows))


def test_species_corrections_ranges_and_canonical_names():
    t = "un zifio, perdón, era un cachalote; calderones grises unos doce, perdón, catorce"
    rows = [{"name": "Zifio", "sci": "Ziphius cavirostris", "count": 1, "source": "un zifio"},
            {"name": "Cachalote", "sci": "Physeter macrocephalus", "count": 1, "source": "era un cachalote"},
            {"name": "Risso", "sci": "Grampus griseus", "count": 12, "source": "calderones grises unos doce"}]
    got = {r["sci"]: r for r in verify.check_species_rows(sp.clean_ai_rows(rows, t), t, lang="es", tally=t)[0]}
    assert "Ziphius cavirostris" not in got and got["Grampus griseus"]["count"] == 14
    assert got["Grampus griseus"]["name"] == "Calderón gris"  # the standard name, not the model's
    t = "unos 15 con 3 crías de calderones tropicales"
    r = verify.check_species_rows(sp.clean_ai_rows([{"name": "Ballena piloto tropical", "sci": "Globicephala macrorhynchus",
                                                      "count": 18, "source": t}], t), t, lang="es")[0][0]
    assert r["count"] == 15 and r["name"] == "Calderón tropical"


def test_round6_fixes():
    # "un par de alcatraces" quoted only as "alcatraces": the pair still counts
    t = "vimos un cacha lote enorme y luego tres no cuatro delfines moteados una tortuga voba y un par de alcatraces"
    rows = verify.check_species_rows(sp.clean_ai_rows(
        [{"name": "Alcatraz", "sci": "Morus bassanus", "count": 2, "source": "alcatraces"}], t), t, lang="es")[0]
    assert rows[0]["count"] == 2
    # species names are not details; Spanish "sea" is a verb
    turtle = [S(name="Loggerhead Sea Turtle", sci="Caretta caretta", count=1, sure=True, heard=False, star=True)]
    assert verify.check_text("We were thrilled to spot a Loggerhead Sea Turtle, the highlight of the outing.", lang="en",
                             species=turtle, notes="a loggerhead turtle!") == []
    boba = [S(name="Tortuga boba", sci="Caretta caretta", count=2, sure=True, heard=False, star=False)]
    assert verify.check_text("Vimos dos tortugas bobas, algo que hace que cada salida sea única.", lang="es",
                             species=boba, notes="2 tortugas bobas") == []
    # positions and an unmarked "highlight"
    p = verify.check_text("A su alrededor descansaban dos tortugas bobas, lo más destacado del día.", lang="es",
                          species=boba, notes="2 tortugas bobas")
    assert {x["kind"] for x in p} == {"detail", "claim"}


def test_checker_outage_is_reported_not_hidden(monkeypatch):
    from app.services.drafting import checked_draft

    def down(*a, **k):
        raise ai.AIError("rate_limited")
    monkeypatch.setattr(ai, "unsupported_claims", down)
    monkeypatch.setattr(ai, "proofread", down)
    res = checked_draft(lambda prev, probs: "Vimos dos tortugas bobas.", lambda t: [], "2 tortugas bobas", "", "es")
    assert {"kind": "unchecked", "what": ""} in res["problems"]


def test_stored_flags_show_until_the_guide_edits(owner, monkeypatch):
    monkeypatch.setattr(settings, "llm_api_key", "gsk_test")
    monkeypatch.setattr(ai, "draft_day", lambda **kw: ("We had a quiet morning with friends.", 1, 1))
    monkeypatch.setattr(ai, "unsupported_claims", lambda t, n, s: ([{"quote": "with friends", "why": "not in notes"}], 1, 1))
    monkeypatch.setattr(ai, "proofread", lambda t, l: (t, 1, 1))
    tid = new_trip(owner)
    did = add_day(owner, tid)
    owner.post_form(f"/app/trips/{tid}/days/{did}/draft", {"place": "", "notes": "quiet morning"})
    page = owner.get(f"/app/trips/{tid}?tab=days&day={did}").text
    assert "with friends" in page and "Check before approving" in page
    owner.post_form(f"/app/trips/{tid}/days/{did}", {"place": "", "notes": "quiet morning", "narrative": "A quiet morning."})
    assert "Check before approving" not in owner.get(f"/app/trips/{tid}?tab=days&day={did}").text


def test_round7_fixes():
    # the AI called "delfines comunes, muchísimos, más de 100" bottlenose; the guide's words win
    t = "Más tarde delfines comunes, muchísimos, más de 100, saltando. No vimos delfines mulares hoy."
    rows = verify.check_species_rows(sp.clean_ai_rows([{"name": "Delfín mular", "sci": "Tursiops truncatus", "count": 100,
                                                        "source": "delfines comunes, muchísimos, más de 100"}], t), t, lang="es")[0]
    assert [(r["sci"], r["count"]) for r in rows] == [("Delphinus delphis", 100)]
    # a misspelt scientific name snaps to the real one
    t = "unos quince delfines comunes"
    rows = verify.check_species_rows(sp.clean_ai_rows([{"name": "Delfín común", "sci": "Delphinus delphinus", "count": 15,
                                                        "source": t}], t), t, lang="es")[0]
    assert rows[0]["sci"] == "Delphinus delphis"
    # "No otters were present today" is fine when the notes say so
    sp_ = [S(name="Griffon Vulture", sci="Gyps fulvus", count=40, sure=True, heard=False, star=False)]
    assert verify.check_text("We saw 40 Griffon Vultures. No otters were present today.", lang="en", species=sp_,
                             notes="40 grifons, no otters today") == []
    # Spanish writes common names in lower case
    assert verify.tidy("Vimos catorce Calderones Grises y un Zifio De Cuvier.", "es") == \
        "Vimos catorce calderones grises y un zifio de Cuvier."


def test_round8_fixes():
    t = "40 grifons, 6 black vultures, imperial eagle pair!, links x1"
    rows = verify.check_species_rows(sp.clean_ai_rows([{"name": "Imperial Eagle", "sci": "Aquila adalberti", "count": 2,
                                                        "source": "imperial eagle"}], t), t, lang="en")[0]
    eagle = next(r for r in rows if r["sci"] == "Aquila adalberti")
    assert eagle["count"] == 2 and eagle["star"] is True
    t = "un zifio, perdón, era un cachalote; 6 delfines moteados"
    rows = verify.check_species_rows(sp.clean_ai_rows([{"name": "Delfín moteado", "sci": "Stenella frontalis", "count": 6,
                                                        "sure": False, "star": True, "source": "6 delfines moteados"}], t),
                                     t, lang="es")[0]
    assert rows[0]["sure"] is True and rows[0]["star"] is False
    magpie = [S(name="Iberian Magpie", sci="Cyanopica cooki", count=12, sure=True, heard=False, star=False)]
    assert {"kind": "detail", "what": "bright"} in verify.check_text(
        "Twelve Iberian Magpies with their bright azure wings completed the group.", lang="en", species=magpie,
        notes="azure winged magpies 12")
    assert verify.tidy("We heard an eurasian eagle-owl.", "en") == "We heard a Eurasian eagle-owl."
