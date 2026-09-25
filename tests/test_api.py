import json

import pytest

from erbuild import api


@pytest.fixture
def enemy_api(enemy_workbook):
    """The API with the synthetic enemy workbook loaded, as the web page does."""
    summary = api.load_enemy_workbook(enemy_workbook.read_bytes())
    assert summary["placements"] == 6
    yield api
    api._enemy_data = api._enemy_raw = None


def test_catalog():
    weapons = api.weapons()
    assert len(weapons) > 3000
    blood = next(w for w in weapons if w["name"] == "Blood Uchigatana")
    assert blood["affinity"] == "Blood" and blood["max_upgrade"] == 25
    assert {c["name"] for c in api.classes()} >= {"Samurai", "Wretch"}


def test_attack_rating_matches_cli_example():
    out = api.attack_rating("Blood Uchigatana", {"str": 12, "dex": 40, "arc": 50})
    assert out["damage"] == {"physical": 445}
    assert out["status"] == {"bleed": 110}
    assert out["total"] == 445 and out["unmet_requirements"] == []
    json.dumps(out)  # JSON-ready


def test_errors_come_back_as_data():
    assert "Did you mean" in api.attack_rating("Uchigatan", {})["error"]
    assert "too low" in api.optimize("Uchigatana", "samurai", 1)["error"]


def test_optimize_frontier():
    out = api.optimize("Blood Uchigatana", "samurai", 150, fixed={"vig": 60})
    assert out["status_types"] == ["bleed"]
    assert out["best"]["ar"] == 522 and len(out["frontier"]) > 10
    assert all(abs(b["raw_status"]["bleed"] - b["status"]["bleed"]) < 1 for b in out["frontier"])
    json.dumps(out)


def test_enemy_endpoints(enemy_api):
    assert [e["name"] for e in enemy_api.enemies("knight")] == ["Knight [Boss]"]
    enemy = {"name": "Knight [Boss]", "cycle": "ng+1"}
    ar = enemy_api.attack_rating("Blood Uchigatana", {"dex": 40, "arc": 50}, enemy=enemy)
    assert ar["vs_enemy"]["enemy"]["hp"] == 10000 and ar["vs_enemy"]["total"] > 0
    out = enemy_api.optimize("Blood Uchigatana", "samurai", 120, enemy=enemy, attack_type="slash")
    assert out["best"]["damage"]["total"] >= out["highest_ar"]["damage"]["total"]
    json.dumps(out)


def test_json_bridge():
    out = json.loads(api.call("attack_rating", json.dumps({"weapon": "Uchigatana", "attributes": {"dex": 40}})))
    assert out["total"] > 0
    assert "Unknown method" in json.loads(api.call("nope"))["error"]
    assert "Bad arguments" in json.loads(api.call("optimize", json.dumps({"weapon": "Uchigatana"})))["error"]
    assert "Invalid JSON" in json.loads(api.call("classes", "{"))["error"]


def test_enemy_data_round_trip(enemy_api):
    saved = enemy_api.export_enemy_data()
    enemy_api._enemy_data = enemy_api._enemy_raw = None
    assert enemy_api.load_enemy_data(saved)["placements"] == 6
    assert enemy_api.enemies("soldier")[0]["name"] == "Soldier"
    assert "error" in enemy_api.load_enemy_data("{}")


def test_optimize_includes_class_stats():
    out = api.optimize("Uchigatana", "samurai", 60)
    assert out["class_stats"]["dex"] == 15


# --------------------------------------------------------------------------
# Input checks: UIs send form values as they are; bad ones must come back as
# readable errors, never crashes or silently wrong results.
# --------------------------------------------------------------------------
def test_two_handing_strings_are_parsed_not_truthy():
    one = api.optimize("Uchigatana", "samurai", 150, two_handing="false")
    two = api.optimize("Uchigatana", "samurai", 150, two_handing="true")
    assert one["best"]["ar"] == api.optimize("Uchigatana", "samurai", 150)["best"]["ar"]
    assert two["best"]["ar"] > one["best"]["ar"]
    assert "true or false" in api.optimize("Uchigatana", "samurai", 150, two_handing="yes")["error"]


@pytest.mark.parametrize("kwargs, message", [
    ({"level": None}, "level must be a whole number"),
    ({"level": 150.5}, "level must be a whole number"),
    ({"level": "abc"}, "level must be a whole number"),
    ({"starting_class": None}, "starting_class must be a non-empty string"),
    ({"weapon": None}, "weapon must be a non-empty string"),
    ({"fixed": {"luck": 5}}, "Unknown attribute 'luck'"),
    ({"fixed": {"vig": "sixty"}}, "fixed.vig must be a whole number"),
    ({"fixed": [60]}, "fixed must be an object"),
    ({"minimum": {"dex": 20.5}}, "minimum.dex must be a whole number"),
    ({"upgrade": "x"}, "upgrade must be a whole number"),
])
def test_optimize_rejects_bad_input(kwargs, message):
    args = {"weapon": "Uchigatana", "starting_class": "samurai", "level": 150, **kwargs}
    assert message in api.optimize(**args)["error"]


def test_attack_rating_input_handling():
    base = api.attack_rating("Uchigatana", {})["total"]
    assert api.attack_rating("Uchigatana", {"dex": None})["total"] == base  # empty field = default
    assert api.attack_rating("Uchigatana", {"dex": "10"})["total"] == base
    assert "whole number" in api.attack_rating("Uchigatana", {"dex": 40.7})["error"]
    assert "must be an object" in api.attack_rating("Uchigatana", [])["error"]
    assert "between 1 and 99" in api.attack_rating("Uchigatana", {"dex": 0})["error"]


def test_empty_strings_and_nulls(enemy_api):
    assert "weapon must be a non-empty string" in api.attack_rating("  ", {})["error"]
    assert "enemy.name" in enemy_api.attack_rating("Uchigatana", {}, enemy={"name": None})["error"]
    assert "enemy must be an object" in enemy_api.attack_rating("Uchigatana", {}, enemy="Knight")["error"]
    ok = enemy_api.attack_rating("Uchigatana", {}, enemy={"name": "Knight [Boss]", "cycle": None})
    assert ok["vs_enemy"]["enemy"]["cycle"] == "NG"
    assert "Motion value" in enemy_api.attack_rating(
        "Uchigatana", {}, enemy={"name": "Knight [Boss]"}, motion_value=0)["error"]
    assert len(enemy_api.enemies(None)) == 6
    assert len(enemy_api.enemies("", limit=-1)) == 1


def test_enemy_variant_via_api(enemy_api):
    spec = {"name": "Mage", "location": "Tower"}
    assert "variant number" in enemy_api.attack_rating("Uchigatana", {}, enemy=spec)["error"]
    out = enemy_api.attack_rating("Uchigatana", {}, enemy={**spec, "variant": 2})
    assert out["vs_enemy"]["enemy"]["defense"]["standard"] == 120
