import itertools

import numpy as np
import pytest

from erbuild import attack_power, attack_rating, load_default, optimize
from erbuild.calculator import type_terms
from erbuild.classes import STARTING_CLASSES, get_class
from erbuild.constants import LEVEL_OFFSET, SCALING_ATTRIBUTES
from erbuild.optimizer import TOLERANCE, attribute_bounds


@pytest.fixture(scope="module")
def reg():
    return load_default()


# --------------------------------------------------------------------------
# Brute force oracle: enumerate every allocation of the attributes that matter.
# --------------------------------------------------------------------------
def brute_force(weapon, cls, level, upgrade, two_handing, fixed=None, minimum=None):
    """Best (AR, points used) for every arcane value, by exhaustive enumeration."""
    lo, hi = attribute_bounds(cls, fixed, minimum)
    budget = level + LEVEL_OFFSET - sum(lo.values())
    terms = {t: x for t, x in type_terms(weapon, upgrade).items() if t.is_damage}
    relevant = {a for x in terms.values() for a in (*x.scaling, *x.requires)} | {"arc"}
    stats = [a for a in SCALING_ATTRIBUTES if a in relevant]

    ranges = [np.arange(0, min(hi[a] - lo[a], budget) + 1) for a in stats]
    grid = np.array(np.meshgrid(*ranges, indexing="ij")).reshape(len(stats), -1)
    grid = grid[:, grid.sum(axis=0) <= budget]
    attrs = {a: lo[a] for a in SCALING_ATTRIBUTES}
    for a, row in zip(stats, grid):
        attrs[a] = lo[a] + row
    values = attack_power(weapon, attrs, upgrade, two_handing)
    ar = sum(v for t, v in values.items() if t.is_damage)
    ar = np.broadcast_to(ar, grid.shape[1])
    used = grid.sum(axis=0)
    arc = grid[stats.index("arc")]

    best = {}
    for z in np.unique(arc):
        mask = arc == z
        top = ar[mask].max()
        near = mask & (ar >= top - TOLERANCE)
        best[lo["arc"] + int(z)] = (float(top), int(used[near].min()), budget)
    return best


def pareto(points, status_of):
    """points: {arc: ar}. Independent dominance filter over (AR, status), ties to less arcane."""
    keep = []
    for a, ar in points.items():
        s = status_of(a)
        dominated = False
        for b, br in points.items():
            if b == a:
                continue
            t = status_of(b)
            ge = br >= ar - TOLERANCE and all(x >= y - TOLERANCE for x, y in zip(t, s))
            gt = br > ar + TOLERANCE or any(x > y + TOLERANCE for x, y in zip(t, s))
            if ge and (gt or b < a):
                dominated = True
                break
        if not dominated:
            keep.append(a)
    return sorted(keep)


def _random_cases(n, seed=1234):
    rng = np.random.default_rng(seed)
    reg = load_default()
    weapons = [w for w in reg if any(t.is_damage for t in w.attack[0])]
    classes = list(STARTING_CLASSES.values())
    cases = []
    while len(cases) < n:
        w = weapons[rng.integers(len(weapons))]
        cls = classes[rng.integers(len(classes))]
        upgrade = int(rng.integers(0, w.max_upgrade + 1))
        terms = {t: x for t, x in type_terms(w, upgrade).items() if t.is_damage}
        k = len({a for x in terms.values() for a in (*x.scaling, *x.requires)} | {"arc"})
        cap = {1: 150, 2: 150, 3: 45, 4: 22, 5: 13}[k]
        fixed = {"vig": cls.stats["vig"] + int(rng.integers(0, 30))}
        minimum = {}
        if rng.random() < 0.2:
            a = SCALING_ATTRIBUTES[rng.integers(5)]
            minimum[a] = cls.stats[a] + int(rng.integers(0, 8))
        if rng.random() < 0.1 and "int" not in minimum:
            fixed["int"] = cls.stats["int"] + int(rng.integers(0, 5))
        lo, _ = attribute_bounds(cls, fixed, minimum)
        level = sum(lo.values()) - LEVEL_OFFSET + int(rng.integers(0, cap + 1))
        cases.append((w.key, cls.name, level, upgrade, bool(rng.random() < 0.4), fixed, minimum))
    return cases


@pytest.mark.parametrize("case", _random_cases(200), ids=lambda c: f"{c[0]}-{c[1]}-L{c[2]}")
def test_matches_brute_force(reg, case):
    name, cls_name, level, upgrade, two_handing, fixed, minimum = case
    weapon, cls = reg.get(name), get_class(cls_name)
    result = optimize(
        weapon, cls, level, upgrade=upgrade, two_handing=two_handing, fixed=fixed, minimum=minimum
    )
    oracle = brute_force(weapon, cls, level, upgrade, two_handing, fixed, minimum)

    # Every frontier build is optimal for its arcane value, with the fewest points.
    for build in result.frontier:
        top, used, budget = oracle[build.attributes["arc"]]
        assert build.ar == pytest.approx(top, rel=1e-12, abs=1e-9)
        assert build.free_points == budget - used
        assert sum(build.attributes.values()) + build.free_points == level + LEVEL_OFFSET

    # And the frontier contains exactly the non-dominated arcane values.
    def status_of(arc):
        rating = attack_rating(weapon, {"arc": arc}, upgrade, two_handing)
        return [rating.values.get(t, 0.0) for t in result.status_types]

    expected = pareto({a: v[0] for a, v in oracle.items()}, status_of)
    assert [b.attributes["arc"] for b in result.frontier] == expected


# --------------------------------------------------------------------------
# Behaviour tests.
# --------------------------------------------------------------------------
def test_blood_weapon_frontier_trades_ar_for_bleed(reg):
    result = optimize(reg.get("Blood Uchigatana"), "samurai", 150, fixed={"vig": 60})
    assert len(result.frontier) > 10
    ars = [b.ar for b in result.frontier]
    bleeds = [b.status[result.status_types[0]] for b in result.frontier]
    assert all(x > y for x, y in zip(ars, ars[1:]))
    assert all(x < y for x, y in zip(bleeds, bleeds[1:]))
    assert result.best is result.frontier[0]


def test_with_status_at_least(reg):
    result = optimize(reg.get("Blood Uchigatana"), "samurai", 150, fixed={"vig": 60})
    bleed = result.status_types[0]
    build = result.with_status_at_least(110)
    assert build.status[bleed] >= 110
    assert all(b.ar <= build.ar for b in result.frontier if b.status[bleed] >= 110)
    assert result.with_status_at_least(10_000) is None


def test_no_arcane_status_gives_single_build(reg):
    result = optimize(reg.get("Heavy Claymore"), "vagabond", 120, fixed={"vig": 50})
    assert result.status_types == ()
    assert len(result.frontier) == 1


def test_free_points_when_everything_is_capped(reg):
    weapon = reg.get("Heavy Claymore")  # STR scaling only
    result = optimize(weapon, "wretch", 400)
    best = result.best
    capped = attack_rating(weapon, {a: 99 for a in SCALING_ATTRIBUTES}, weapon.max_upgrade)
    assert best.ar == pytest.approx(capped.total)
    assert best.free_points > 0
    assert best.attributes["int"] == best.attributes["fai"] == best.attributes["arc"] == 10


def test_fixed_and_minimum_are_respected(reg):
    result = optimize(
        reg.get("Blood Uchigatana"), "samurai", 150,
        fixed={"vig": 60, "end": 30}, minimum={"mnd": 20, "fai": 15},
    )
    for b in result.frontier:
        assert b.attributes["vig"] == 60 and b.attributes["end"] == 30
        assert b.attributes["mnd"] >= 20 and b.attributes["fai"] >= 15


def test_invalid_constraints(reg):
    weapon = reg.get("Uchigatana")
    with pytest.raises(ValueError, match="too low"):
        optimize(weapon, "samurai", 5)
    with pytest.raises(ValueError, match="below"):
        optimize(weapon, "samurai", 100, fixed={"vig": 5})
    with pytest.raises(ValueError, match="Unknown attribute"):
        optimize(weapon, "samurai", 100, fixed={"luck": 20})
    with pytest.raises(ValueError, match="too high"):
        optimize(weapon, "samurai", 713, fixed={"vig": 40})
