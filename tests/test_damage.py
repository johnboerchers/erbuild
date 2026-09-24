import numpy as np
import pytest

from erbuild import attack_power, load_default
from erbuild.calculator import type_terms
from erbuild.classes import STARTING_CLASSES, get_class
from erbuild.constants import LEVEL_OFFSET, SCALING_ATTRIBUTES, AttackPowerType
from erbuild.damage import (
    bleed_damage_per_hit,
    bleed_flat_damage,
    bleed_proc_damage,
    damage_per_hit,
    defense_multiplier,
    direct_damage,
    hits_to_proc,
)
from erbuild.enemies import Enemy, EnemyData, convert_workbook, parse_cycle, read_xlsx
from erbuild.optimizer import TOLERANCE, attribute_bounds, optimize_vs_enemy

KEYS = ("standard", "strike", "slash", "pierce", "magic", "fire", "lightning", "holy")
BLEED = AttackPowerType.BLEED


@pytest.fixture(scope="module")
def enemy_data(enemy_workbook):
    return EnemyData(convert_workbook(enemy_workbook))


@pytest.fixture(scope="module")
def reg():
    return load_default()


def make_enemy(defense=100.0, negation=0.0, hp=10_000.0, bleed_res=300.0, bleed_mult=1.0, **kw):
    return Enemy(
        name=kw.get("name", "Test Enemy"),
        location=kw.get("location", "Nowhere"),
        cycle=0,
        npc_id="1",
        hp=hp,
        defense={k: defense for k in KEYS} if np.isscalar(defense) else defense,
        negation={k: negation for k in KEYS} if np.isscalar(negation) else negation,
        resistance={BLEED: bleed_res},
        status_multiplier={BLEED: bleed_mult},
    )


# --------------------------------------------------------------------------
# Defense curve and bleed.
# --------------------------------------------------------------------------
def test_defense_curve_breakpoints_and_continuity():
    for r, expected in [(0.05, 0.1), (0.125, 0.1), (1.0, 0.4), (2.5, 0.7), (8.0, 0.9), (50, 0.9)]:
        assert defense_multiplier(r) == pytest.approx(expected)
    # The published constant 2.552 is rounded, so the curve jumps by ~1e-5 at r = 1.
    for edge in (0.125, 1.0, 2.5, 8.0):
        assert defense_multiplier(edge - 1e-9) == pytest.approx(defense_multiplier(edge), abs=1e-4)
    r = np.linspace(0, 12, 5000)
    damage = r * defense_multiplier(r)  # damage for fixed defense rises with attack
    assert np.all(np.diff(defense_multiplier(r)) >= -1e-12)
    assert np.all(np.diff(damage) > 0)


def test_direct_damage_uses_attack_type_and_negation():
    defense = dict.fromkeys(KEYS, 100.0) | {"slash": 200.0}
    negation = dict.fromkeys(KEYS, 0.0) | {"slash": 50.0, "fire": -20.0}
    enemy = make_enemy(defense=defense, negation=negation)
    values = {AttackPowerType.PHYSICAL: 250.0, AttackPowerType.FIRE: 100.0}
    fire = 100 * 0.4 * 1.2
    assert direct_damage(values, enemy) == pytest.approx(250 * 0.7 + fire)
    slash = 250 * float(defense_multiplier(1.25)) * 0.5
    assert direct_damage(values, enemy, attack_type="slash") == pytest.approx(slash + fire)
    # Motion value scales the attack before the defense curve.
    assert direct_damage(values, enemy, motion_value=200) == pytest.approx(
        500 * float(defense_multiplier(5)) + 200 * float(defense_multiplier(2)) * 1.2
    )
    with pytest.raises(ValueError):
        direct_damage(values, enemy, attack_type="crush")


def test_bleed():
    enemy = make_enemy(hp=20_000, bleed_res=420, bleed_mult=0.7)
    assert bleed_proc_damage(enemy, 100) == pytest.approx(0.7 * (3000 + 100))
    assert hits_to_proc(105, 420) == 4
    assert hits_to_proc(104.9, 420) == 5
    assert hits_to_proc(100, None) == np.inf
    assert bleed_damage_per_hit(105, enemy, 200) == pytest.approx(0.7 * 3200 / 4)
    assert bleed_damage_per_hit(50, make_enemy(bleed_res=None)) == 0


def test_bleed_flat_damage(reg):
    assert bleed_flat_damage(reg.get("Blood Uchigatana"), reg) == 200  # innate bleed + Blood
    assert bleed_flat_damage(reg.get("Uchigatana"), reg) == 100
    assert bleed_flat_damage(reg.get("Blood Broadsword"), reg) == 100  # no innate bleed
    assert bleed_flat_damage(reg.get("Reduvia"), reg) == 200
    assert bleed_flat_damage(reg.get("Rivers of Blood"), reg) == 100


# --------------------------------------------------------------------------
# Enemy data: workbook conversion and lookup (synthetic workbook, no network).
# --------------------------------------------------------------------------
def test_read_xlsx_handles_sparse_cells(tmp_path, xlsx_writer):
    path = tmp_path / "t.xlsx"
    xlsx_writer(path, {"S": [["a", None, 3.0], [None, "b"]]})
    assert read_xlsx(path)["S"] == [["a", None, 3.0], [None, "b"]]


def test_convert_workbook(enemy_data):
    knight = enemy_data.get("knight [boss]", cycle=2)
    assert knight.is_boss and knight.cycle_name == "NG+2"
    assert knight.hp == 15000 and knight.defense["holy"] == 102
    assert knight.negation == {"standard": 10, "strike": 0, "slash": -10, "pierce": 0,
                               "magic": 20, "fire": 0, "lightning": 20, "holy": 40}
    assert knight.resistance[AttackPowerType.POISON] is None  # Immune
    assert knight.resistance[BLEED] == 400
    assert knight.status_multiplier[BLEED] == 0.7
    assert len(enemy_data) == 3  # the row without HP is skipped


def test_enemy_lookup(enemy_data):
    with pytest.raises(KeyError, match="several places"):
        enemy_data.get("Soldier")
    assert enemy_data.get("Soldier", location="cave").hp == 900
    with pytest.raises(KeyError, match="Did you mean: Knight"):
        enemy_data.get("knigt [boss]")
    assert [e.name for e in enemy_data.search("o")][0] == "Knight [Boss]"  # bosses first


def test_parse_cycle():
    assert [parse_cycle(x) for x in ("ng", "NG+", "ng+2", "NG+ 7", "3", 5)] == [0, 1, 2, 7, 3, 5]
    for bad in ("ng+8", "hard", -1):
        with pytest.raises(ValueError):
            parse_cycle(bad)


# --------------------------------------------------------------------------
# Enemy optimizer against brute force.
# --------------------------------------------------------------------------
def brute_force_damage(weapon, cls, level, enemy, upgrade, two_handing, fixed, flat, attack_type):
    lo, hi = attribute_bounds(cls, fixed)
    budget = level + LEVEL_OFFSET - sum(lo.values())
    terms = type_terms(weapon, upgrade)
    stats = [a for a in SCALING_ATTRIBUTES
             if any(a in (*x.scaling, *x.requires) for t, x in terms.items() if t.is_damage or t == BLEED)]
    if not stats:
        stats = ["str"]
    ranges = [np.arange(0, min(hi[a] - lo[a], budget) + 1) for a in stats]
    grid = np.array(np.meshgrid(*ranges, indexing="ij")).reshape(len(stats), -1)
    grid = grid[:, grid.sum(axis=0) <= budget]
    attrs = {a: lo[a] for a in SCALING_ATTRIBUTES}
    for a, row in zip(stats, grid):
        attrs[a] = lo[a] + row
    values = attack_power(weapon, attrs, upgrade, two_handing)
    return float(np.max(damage_per_hit(values, enemy, 100, attack_type, flat)))


def _random_enemy_cases(n, seed=7):
    rng = np.random.default_rng(seed)
    reg = load_default()
    weapons = [w for w in reg if any(t.is_damage for t in w.attack[0])]
    classes = list(STARTING_CLASSES.values())
    cases = []
    while len(cases) < n:
        w = weapons[rng.integers(len(weapons))]
        upgrade = int(rng.integers(0, w.max_upgrade + 1))
        terms = type_terms(w, upgrade)
        k = len({a for t, x in terms.items() if t.is_damage or t == BLEED
                 for a in (*x.scaling, *x.requires)})
        if k > 4:
            continue
        cls = classes[rng.integers(len(classes))]
        fixed = {"vig": cls.stats["vig"] + int(rng.integers(0, 20))}
        lo, _ = attribute_bounds(cls, fixed)
        cap = {0: 60, 1: 120, 2: 90, 3: 35, 4: 16}[k]
        level = sum(lo.values()) - LEVEL_OFFSET + int(rng.integers(0, cap + 1))
        enemy = {
            "defense": {key: float(rng.uniform(40, 220)) for key in KEYS},
            "negation": {key: float(rng.uniform(-30, 70)) for key in KEYS},
            "hp": float(rng.uniform(500, 30000)),
            "bleed_res": None if rng.random() < 0.2 else float(rng.uniform(80, 900)),
            "bleed_mult": float(rng.choice([0.5, 0.7, 1.0])),
        }
        attack_type = str(rng.choice(["standard", "strike", "slash", "pierce"]))
        cases.append((w.key, cls.name, level, upgrade, bool(rng.random() < 0.4), fixed, enemy, attack_type))
    return cases


@pytest.mark.parametrize("case", _random_enemy_cases(120), ids=lambda c: f"{c[0]}-L{c[2]}")
def test_enemy_optimizer_matches_brute_force(reg, case):
    name, cls_name, level, upgrade, two_handing, fixed, enemy_kw, attack_type = case
    weapon, cls, enemy = reg.get(name), get_class(cls_name), make_enemy(**enemy_kw)
    flat = bleed_flat_damage(weapon, reg)
    expected = brute_force_damage(weapon, cls, level, enemy, upgrade, two_handing, fixed, flat, attack_type)
    methods = ["enumeration"]
    if sum(t.is_damage for t in type_terms(weapon, upgrade)) <= 1:
        methods.append("frontier")
    for method in methods:
        result = optimize_vs_enemy(
            weapon, cls, level, enemy, upgrade=upgrade, two_handing=two_handing,
            fixed=fixed, attack_type=attack_type, method=method,
        )
        best = result.best
        assert best.damage.total == pytest.approx(expected, rel=1e-9, abs=1e-6), method
        assert sum(best.build.attributes.values()) + best.build.free_points == level + LEVEL_OFFSET
        assert best.damage.total >= result.highest_ar.damage.total - TOLERANCE


def test_enemy_optimizer_prefers_arcane_against_bleedable_boss(reg):
    weapon = reg.get("Blood Uchigatana")
    boss = make_enemy(defense=120, negation=10, hp=18_000, bleed_res=420, bleed_mult=0.7)
    immune = make_enemy(defense=120, negation=10, hp=18_000, bleed_res=None)
    vs_boss = optimize_vs_enemy(weapon, "samurai", 150, boss, fixed={"vig": 60})
    vs_immune = optimize_vs_enemy(weapon, "samurai", 150, immune, fixed={"vig": 60})
    assert vs_boss.method == "frontier"
    assert vs_boss.best.build.attributes["arc"] > vs_immune.best.build.attributes["arc"]
    assert vs_boss.best.damage.total > vs_boss.highest_ar.damage.total
    assert vs_immune.best.damage.bleed_per_hit == 0
