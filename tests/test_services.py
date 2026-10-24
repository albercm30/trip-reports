from types import SimpleNamespace as S

from app.services.freedraft import day_draft, intro_summary, tidy_notes
from app.services.species import clean_ai_rows, parse_tally


def test_parse_tally_counts_and_flags():
    rows = {r["name"]: r for r in parse_tally(
        "40 griffon vultures, spanish imperial eagle pair, lynx x1!, heard eagle owl, some warblers, "
        "Bonelli's eagle?, iberian magpie (20), red deer 35, 3 mouflons\nuna pareja de cigüeñas negras")}
    assert rows["Griffon vulture"]["count"] == 40
    assert rows["Spanish imperial eagle"]["count"] == 2
    assert rows["Lynx"]["count"] == 1 and rows["Lynx"]["star"]
    assert rows["Eagle owl"]["heard"]
    assert not rows["Warbler"]["sure"]
    assert not rows["Bonelli's eagle"]["sure"]
    assert rows["Iberian magpie"]["count"] == 20 and rows["Red deer"]["count"] == 35
    assert rows["Cigüeña negra"]["count"] == 2


def test_parse_tally_merges_duplicates():
    rows = parse_tally("5 hoopoes\nhoopoe x8")
    assert len(rows) == 1 and rows[0]["count"] == 8


def test_clean_ai_rows_rejects_junk():
    rows = clean_ai_rows([{"name": "Lynx", "count": "2.0"}, {"name": ""}, "x", {"name": "Owl", "count": "lots", "sure": False}])
    assert [r["name"] for r in rows] == ["Lynx", "Owl"]
    assert rows[0]["count"] == 2 and rows[1]["count"] is None and rows[1]["sure"] is False
    assert clean_ai_rows({"not": "a list"}) == []


def test_tidy_notes_expands_shorthand_without_adding():
    out = tidy_notes("met group 8am\neagle pair ~11. lynx ~300m, 6 min in scopes!!", "en")
    assert out == "Met group 8am. Eagle pair around 11:00. Lynx about 300 m, 6 minutes in scopes!"


def test_day_draft_mentions_only_listed_species():
    sp = [S(name="Iberian Lynx", sci="Lynx pardinus", count=1, heard=False, sure=True, star=True),
          S(name="Eurasian Eagle-Owl", sci="Bubo bubo", count=None, heard=True, sure=True, star=False),
          S(name="Bonelli's Eagle", sci="Aquila fasciata", count=1, heard=False, sure=False, star=False)]
    text = day_draft(2, "La Lastrilla", "Rain after lunch", sp, "en")
    assert text.startswith("Day 2 took us to La Lastrilla.")
    assert "highlight was Iberian lynx" in text and "heard Eurasian eagle-owl" in text
    assert "possible Bonelli's eagle" in text and "3 species" in text
    es = day_draft(1, "", "Lluvia por la tarde", sp, "es")
    assert "En total, registramos 3 especies hoy." in es


def test_intro_summary():
    intro, summary = intro_summary("Lynx Weekend", "Andújar", 3, ["Iberian Lynx"], 15, "en")
    assert intro.startswith("Lynx Weekend: 3 days in Andújar.")
    assert "15 species" in summary and "Iberian lynx" in summary
