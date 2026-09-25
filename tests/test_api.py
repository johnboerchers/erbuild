import json

import pytest

from erbuild import api


@pytest.fixture
def enemy_api(enemy_workbook):
    """The API with the synthetic enemy workbook loaded, as the web page does."""
    summary = api.load_enemy_workbook(enemy_workbook.read_bytes())
    assert summary["placements"] == 3
    yield api
    api._enemy_data = None


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
