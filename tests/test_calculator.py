import csv
import json
from pathlib import Path

import numpy as np
import pytest

from erbuild import AttackPowerType, attack_power, attack_rating, load_default
from erbuild.classes import STARTING_CLASSES
from erbuild.constants import LEVEL_OFFSET

FIXTURES = Path(__file__).parent / "fixtures"


@pytest.fixture(scope="module")
def reg():
    return load_default()


# --------------------------------------------------------------------------
# Differential test against the reference TypeScript implementation.
# --------------------------------------------------------------------------
REFERENCE = json.loads((FIXTURES / "reference_ar.json").read_text())["cases"]


@pytest.mark.parametrize("case", REFERENCE, ids=lambda c: f"{c['weapon']}+{c['upgrade']}")
def test_matches_reference_implementation(reg, case):
    weapon = reg.get(case["weapon"])
    ar = attack_rating(weapon, case["attributes"], case["upgrade"], case["twoHanding"])
    expected = {AttackPowerType(int(k)): v for k, v in case["attackPower"].items()}
    assert set(ar.values) == set(expected)
    for t, v in expected.items():
        assert ar.values[t] == pytest.approx(v, rel=1e-12, abs=1e-9)
    assert sorted(ar.ineffective_attributes) == sorted(case["ineffectiveAttributes"])


# --------------------------------------------------------------------------
# In-game spot checks: values read directly off the equipment screen.
# See tests/fixtures/ingame_ar.csv for how to add more.
# --------------------------------------------------------------------------
def _ingame_rows():
    path = FIXTURES / "ingame_ar.csv"
    with path.open() as f:
        rows = [r for r in csv.DictReader(line for line in f if not line.startswith("#"))]
    return rows


@pytest.mark.parametrize("row", _ingame_rows(), ids=lambda r: f"{r['weapon']}+{r['upgrade']}")
def test_matches_in_game(reg, row):
    weapon = reg.get(row["weapon"])
    attrs = {a: int(row[a]) for a in ("str", "dex", "int", "fai", "arc")}
    ar = attack_rating(weapon, attrs, int(row["upgrade"]), row["two_handing"].lower() == "true")
    shown = ar.displayed
    for col, t in [("physical", AttackPowerType.PHYSICAL), ("magic", AttackPowerType.MAGIC),
                   ("fire", AttackPowerType.FIRE), ("lightning", AttackPowerType.LIGHTNING),
                   ("holy", AttackPowerType.HOLY), ("bleed", AttackPowerType.BLEED)]:
        if row.get(col):
            assert shown.get(t, 0) == int(row[col]), f"{col}: got {shown.get(t, 0)}"


# --------------------------------------------------------------------------
# Structural / property tests.
# --------------------------------------------------------------------------
def test_loads_all_weapons(reg):
    assert len(reg) > 3000
    assert reg.get("blood uchigatana").name == "Blood Uchigatana"


def test_unknown_weapon_suggests(reg):
    with pytest.raises(KeyError, match="Did you mean"):
        reg.get("Blood Uchigatanna")


def test_curves_monotone_and_bounded(reg):
    for weapon in list(reg)[:200]:
        for curve in weapon.curves.values():
            assert np.all(np.diff(curve[1:]) >= -1e-12)
            assert curve[1] == pytest.approx(0.0)


def test_vectorized_matches_scalar(reg):
    weapon = reg.get("Blood Uchigatana")
    rng = np.random.default_rng(0)
    stats = {a: rng.integers(1, 100, size=500) for a in ("str", "dex", "int", "fai", "arc")}
    vec = attack_power(weapon, stats, 25, two_handing=True)
    for i in range(0, 500, 37):
        single = attack_rating(weapon, {a: int(v[i]) for a, v in stats.items()}, 25, True)
        for t, v in single.values.items():
            assert vec[t][i] == pytest.approx(v)


def test_unmet_requirement_penalty(reg):
    weapon = reg.get("Blood Uchigatana")  # requires STR 11, DEX 15
    ok = attack_rating(weapon, {"str": 11, "dex": 15, "arc": 10}, 0)
    bad = attack_rating(weapon, {"str": 10, "dex": 15, "arc": 10}, 0)
    assert bad.ineffective_attributes == ("str",)
    base = weapon.attack[0][AttackPowerType.PHYSICAL]
    assert bad.values[AttackPowerType.PHYSICAL] == pytest.approx(base * 0.6)
    assert ok.values[AttackPowerType.PHYSICAL] > bad.values[AttackPowerType.PHYSICAL]


def test_two_handing_fixes_str_requirement(reg):
    weapon = reg.get("Blood Uchigatana")  # STR 11 required; floor(1.5 * 8) = 12
    assert attack_rating(weapon, {"str": 8, "dex": 15}, 0).ineffective_attributes == ("str",)
    assert attack_rating(weapon, {"str": 8, "dex": 15}, 0, True).ineffective_attributes == ()


def test_status_ignores_two_handing(reg):
    weapon = reg.get("Blood Uchigatana")
    stats = {"str": 30, "dex": 30, "arc": 40}
    one = attack_rating(weapon, stats, 25)
    two = attack_rating(weapon, stats, 25, True)
    assert one.values[AttackPowerType.BLEED] == two.values[AttackPowerType.BLEED]
    assert two.values[AttackPowerType.PHYSICAL] > one.values[AttackPowerType.PHYSICAL]


def test_invalid_inputs(reg):
    weapon = reg.get("Rivers of Blood")
    with pytest.raises(ValueError):
        attack_rating(weapon, {"str": 20}, upgrade=11)
    with pytest.raises(ValueError):
        attack_rating(weapon, {"str": 100})


def test_starting_classes_level_identity():
    assert len(STARTING_CLASSES) == 10
    for c in STARTING_CLASSES.values():
        assert sum(c.stats.values()) - LEVEL_OFFSET == c.level


def test_weapon_lookup_and_search_edges(reg):
    with pytest.raises(KeyError, match="Enter a weapon name"):
        reg.get("   ")
    assert reg.get("  Uchigatana ").name == "Uchigatana"
    assert reg.search("uchigatana", limit=0) == []
    assert reg.search("uchigatana", limit=-1) == []


def test_regulation_load_errors(tmp_path):
    from erbuild import Regulation

    with pytest.raises(ValueError, match="Can't read weapon data"):
        Regulation.load(tmp_path / "missing.json")
    bad = tmp_path / "regulation-bad.json"
    bad.write_text('{"weapons": []}')
    with pytest.raises(ValueError, match="isn't erbuild weapon data"):
        Regulation.load(bad)
