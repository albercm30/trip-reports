from types import SimpleNamespace as S

from app.services.freedraft import day_draft, intro_summary, tidy_notes
from app.services.species import clean_ai_rows, parse_tally


def test_parse_tally_counts_and_flags():
    rows = {r["name"]: r for r in parse_tally(
        "40 griffon vultures, spanish imperial eagle pair, lynx x1!, heard eagle owl, some warblers, "
        "Bonelli's eagle?, iberian magpie (20), red deer 35, 3 mouflons\nuna pareja de cigüeñas negras")}
    assert rows["Griffon Vulture"]["count"] == 40 and rows["Griffon Vulture"]["sci"] == "Gyps fulvus"
    assert rows["Spanish Imperial Eagle"]["count"] == 2
    assert rows["Iberian Lynx"]["count"] == 1 and rows["Iberian Lynx"]["star"]
    assert rows["Eurasian Eagle-Owl"]["heard"]
    assert not rows["Warbler"]["sure"] and rows["Warbler"]["sci"] == ""  # vague: never guessed
    assert not rows["Bonelli's Eagle"]["sure"]
    assert rows["Iberian Magpie"]["count"] == 20 and rows["Red Deer"]["count"] == 35
    assert rows["Black Stork"]["count"] == 2


def test_messy_typing_and_dictation():
    rows = {r["name"]: r for r in parse_tally(
        "um so fourty grifon vultures two blak vultures imperial eagle pair links times one heard eagle owl "
        "some kind of warbler, spoonbils 12, purple swamp hen x4, kingfischer, 3 no 4 mufflons, no lynx today")}
    assert rows["Griffon Vulture"]["count"] == 40 and rows["Griffon Vulture"]["source"] == "40 grifon vultures"
    assert rows["Cinereous Vulture"]["count"] == 2
    assert rows["Spanish Imperial Eagle"]["count"] == 2
    assert rows["Iberian Lynx"]["count"] == 1  # "links" is how phones hear "lynx"
    assert rows["Eurasian Eagle-Owl"]["heard"]
    assert rows["Eurasian Spoonbill"]["count"] == 12
    assert rows["Western Swamphen"]["count"] == 4
    assert "Common Kingfisher" in rows
    assert rows["Mouflon"]["count"] == 4  # "3 no 4": the correction wins
    assert not rows["Warbler"]["sure"]
    assert len(rows) == 10  # "no lynx today" adds nothing


def test_trailing_counts_and_spanish():
    rows = {r["name"]: r for r in parse_tally("griffon vulture forty black vulture six imperial eagle two!")}
    assert rows["Griffon Vulture"]["count"] == 40 and rows["Cinereous Vulture"]["count"] == 6
    assert rows["Spanish Imperial Eagle"]["count"] == 2 and rows["Spanish Imperial Eagle"]["star"]
    es = {r["name"]: r for r in parse_tally(
        "cuarenta y dos buitres leonados y una pareja de imperiales, lince por uno, oímos búho real, no vimos nutria",
        lang="es")}
    assert es["Buitre leonado"]["count"] == 42 and es["Águila imperial ibérica"]["count"] == 2
    assert es["Lince ibérico"]["count"] == 1 and es["Búho real"]["heard"]
    assert "Nutria" not in es


def test_operator_vocabulary_is_learned():
    from app.services.species import Vocab
    v = Vocab([("Barbary Ground Squirrel", "Atlantoxerus getulus", "mammals")])
    rows = parse_tally("barbery ground squirels 3", v)
    assert rows[0]["name"] == "Barbary Ground Squirrel" and rows[0]["count"] == 3


def test_parse_tally_merges_duplicates():
    rows = parse_tally("5 hoopoes\nhoopoe x8")
    assert len(rows) == 1 and rows[0]["count"] == 8


def test_clean_ai_rows_rejects_junk_and_inventions():
    raw = "lynx x2, some owl, fourty grifon vultures"
    rows = clean_ai_rows({"species": [
        {"name": "Iberian Lynx", "count": "2.0", "source": "lynx x2"},
        {"name": ""}, "x",
        {"name": "Owl", "count": "lots", "sure": False, "source": "some owl"},
        {"name": "Griffon Vulture", "sci": "Gyps fulvus", "count": 40, "source": "forty griffon vultures"},
        {"name": "Golden Eagle", "sci": "Aquila chrysaetos", "source": "golden eagle"},  # never said
    ]}, raw)
    assert [r["name"] for r in rows] == ["Iberian Lynx", "Owl", "Griffon Vulture"]
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
