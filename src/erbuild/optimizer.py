"""Stat allocation optimizer.

Given a starting class, a target level, a weapon context (weapon, upgrade level, grip)
and any fixed or minimum attributes, find the allocations that maximize attack rating
(AR). For weapons whose status buildup scales with arcane (bleed, poison, madness,
sleep), the result is the Pareto frontier of AR vs. buildup: for each amount of
buildup, the best AR you can have with it.

Method (see the README for the full formulation):

1. Buildup depends only on raw arcane, so each arcane value gives one buildup value.
   The frontier is a sweep over arcane: for each value a, maximize AR with ARC = a.
2. Once we fix which requirements are met, AR is a constant plus one lookup table
   per attribute. Maximizing a sum of per-attribute tables under a point budget is a
   nonlinear integer knapsack, which dynamic programming solves exactly. One DP over
   STR/DEX/INT/FAI answers every arcane value at once:

       AR(a) = C + h_arc(a) + V(N - a)

3. Requirements are the only thing coupling attributes, so we enumerate which
   requirements are treated as met (at most 2^5 cases) and keep the best.

Ties are broken toward spending fewer points; unspent points are reported as free.
"""

from __future__ import annotations

import itertools
from collections.abc import Mapping
from dataclasses import dataclass

import numpy as np

from .calculator import (
    INEFFECTIVE_ATTRIBUTE_PENALTY,
    AttackRating,
    attack_power,
    attack_rating,
    gets_two_handing_bonus,
    type_terms,
)
from .classes import StartingClass, get_class
from .constants import (
    ALL_ATTRIBUTES,
    LEVEL_OFFSET,
    MAX_ATTRIBUTE,
    MAX_EFFECTIVE_ATTRIBUTE,
    SCALING_ATTRIBUTES,
    AttackPowerType,
)
from .damage import HitDamage, bleed_flat_damage, damage_per_hit, hit_breakdown
from .enemies import ATTACK_TYPES, Enemy
from .regulation import Regulation, Weapon, load_default

#: Two AR values closer than this are treated as equal (guards against float noise).
TOLERANCE = 1e-9

_ARCANE = "arc"
_DP_ATTRIBUTES = tuple(a for a in SCALING_ATTRIBUTES if a != _ARCANE)


@dataclass(frozen=True)
class Build:
    """One optimal allocation of all eight attributes."""

    attributes: dict[str, int]
    rating: AttackRating
    #: Points the level allows but that don't raise AR. Put them anywhere.
    free_points: int

    @property
    def ar(self) -> float:
        """Unrounded total damage AR (the optimization objective)."""
        return self.rating.total

    @property
    def status(self) -> dict[AttackPowerType, float]:
        return self.rating.status


@dataclass(frozen=True)
class OptimizationResult:
    weapon: Weapon
    upgrade: int
    two_handing: bool
    starting_class: StartingClass
    level: int
    #: Status types whose buildup scales with arcane; the frontier trades AR against these.
    status_types: tuple[AttackPowerType, ...]
    #: Pareto-optimal builds, in increasing arcane (and so increasing buildup).
    frontier: tuple[Build, ...]

    @property
    def best(self) -> Build:
        """The build with the highest AR (ignoring status buildup)."""
        top = max(b.ar for b in self.frontier)
        # Among (near-)ties on AR, the frontier is ordered by buildup; take the most.
        return [b for b in self.frontier if b.ar >= top - TOLERANCE][-1]

    def with_status_at_least(
        self, value: float, status: AttackPowerType | None = None
    ) -> Build | None:
        """Highest-AR build whose buildup of `status` is at least `value`, if any.

        `status` defaults to the weapon's only arcane-scaling status type.
        """
        if status is None:
            if len(self.status_types) != 1:
                raise ValueError(f"Specify a status type: one of {self.status_types}")
            status = self.status_types[0]
        ok = [b for b in self.frontier if b.status.get(status, 0.0) >= value - TOLERANCE]
        return max(ok, key=lambda b: b.ar) if ok else None


# ---------------------------------------------------------------------- constraints
def attribute_bounds(
    starting_class: StartingClass,
    fixed: Mapping[str, int] | None = None,
    minimum: Mapping[str, int] | None = None,
) -> tuple[dict[str, int], dict[str, int]]:
    """Lower and upper bound for each attribute from the class, fixed values and minimums."""
    fixed = _normalize(fixed)
    minimum = _normalize(minimum)
    lo = dict(starting_class.stats)
    hi = {a: MAX_ATTRIBUTE for a in ALL_ATTRIBUTES}
    for a, v in minimum.items():
        lo[a] = max(lo[a], v)
    for a, v in fixed.items():
        if v < lo[a]:
            reason = (
                f"the minimum of {minimum[a]}" if minimum.get(a, 0) > starting_class.stats[a]
                else f"the {starting_class.name} base of {starting_class.stats[a]}"
            )
            raise ValueError(f"{a.upper()} is fixed at {v}, below {reason}")
        lo[a] = hi[a] = v
    return lo, hi


def _normalize(values: Mapping[str, int] | None) -> dict[str, int]:
    out = {}
    for a, v in (values or {}).items():
        key = a.strip().lower()
        if key not in ALL_ATTRIBUTES:
            raise ValueError(f"Unknown attribute {a!r}. Options: {', '.join(ALL_ATTRIBUTES)}")
        if not 1 <= int(v) <= MAX_ATTRIBUTE:
            raise ValueError(f"{key.upper()} must be between 1 and {MAX_ATTRIBUTE}")
        out[key] = int(v)
    return out


# ---------------------------------------------------------------------- the DP
@dataclass
class _Case:
    """One requirement case: which requirements are met, and the resulting tables."""

    constant: float
    #: tables[a][z] = AR contributed by attribute a at (lower bound + z); -inf if disallowed.
    tables: dict[str, np.ndarray]
    #: history[k] = V before adding _DP_ATTRIBUTES[k]; history[-1] is the final V.
    history: list[np.ndarray]


def _effective(values: np.ndarray, attribute: str, str_bonus: bool) -> np.ndarray:
    if attribute == "str" and str_bonus:
        return np.minimum((values * 3) // 2, MAX_EFFECTIVE_ATTRIBUTE)
    return values


def _build_cases(
    weapon: Weapon,
    upgrade: int,
    two_handing: bool,
    lo: Mapping[str, int],
    hi: Mapping[str, int],
    budget: int,
) -> list[_Case]:
    terms = {t: term for t, term in type_terms(weapon, upgrade).items() if t.is_damage}
    str_bonus = gets_two_handing_bonus(weapon, two_handing)

    # Values each damage attribute can take: lo..min(hi, lo + budget).
    values = {
        a: np.arange(lo[a], min(hi[a], lo[a] + budget) + 1, dtype=np.int64)
        for a in SCALING_ATTRIBUTES
    }
    effective = {a: _effective(v, a, str_bonus) for a, v in values.items()}
    met = {
        a: effective[a] >= weapon.requirements[a]
        for a in {a for term in terms.values() for a in term.requires}
    }
    # Requirements that can go either way within the bounds need a case split.
    split = sorted(a for a, m in met.items() if m.any() and not m.all())

    cases = []
    for k in range(len(split) + 1):
        for chosen in itertools.combinations(split, k):
            case = _build_case(terms, values, effective, met, set(chosen), set(split), budget)
            if case is not None:
                cases.append(case)
    return cases


def _build_case(terms, values, effective, met, chosen, split, budget) -> _Case | None:
    def is_met(a: str) -> bool:
        return a in chosen if a in split else bool(met[a].all())

    constant = 0.0
    tables = {a: np.zeros(len(v)) for a, v in values.items()}
    for term in terms.values():
        if all(is_met(a) for a in term.requires):
            constant += term.base
            for a, s in term.scaling.items():
                tables[a] = tables[a] + term.base * s * term.curve[effective[a]]
        else:
            constant += term.base * (1.0 - INEFFECTIVE_ATTRIBUTE_PENALTY)

    # Restrict split attributes to the side of their requirement this case assumes.
    for a in split:
        allowed = met[a] if a in chosen else ~met[a]
        tables[a] = np.where(allowed, tables[a], -np.inf)

    v = np.zeros(budget + 1)
    history = []
    for a in _DP_ATTRIBUTES:
        history.append(v)
        v = _max_plus(v, tables[a])
    history.append(v)
    if np.isneginf(v[-1]):
        return None
    return _Case(constant, tables, history)


def _max_plus(v: np.ndarray, h: np.ndarray) -> np.ndarray:
    """out[n] = max over z <= n of h[z] + v[n - z]."""
    n = np.arange(len(v))[:, None]
    z = np.arange(len(h))[None, :]
    idx = n - z
    cand = np.where(idx >= 0, h[z] + v[np.clip(idx, 0, None)], -np.inf)
    return cand.max(axis=1)


def _backtrack(case: _Case, points: int) -> tuple[dict[str, int], int]:
    """Cheapest allocation of `points` over the DP attributes reaching the optimum.

    Returns extra points per attribute (above its lower bound) and the total used.
    """
    final = case.history[-1]
    # Smallest budget that already reaches the best value (V is nondecreasing).
    n = int(np.argmax(final[: points + 1] >= final[points] - TOLERANCE))
    used = n
    extra = {}
    for k in range(len(_DP_ATTRIBUTES) - 1, -1, -1):
        a = _DP_ATTRIBUTES[k]
        before, after = case.history[k], case.history[k + 1]
        h = case.tables[a][: n + 1]
        cand = h + before[n - np.arange(len(h))]
        z = int(np.argmax(cand >= after[n] - TOLERANCE))
        extra[a] = z
        n -= z
    return extra, used - n


# ---------------------------------------------------------------------- public API
def _as_class(starting_class: StartingClass | str) -> StartingClass:
    return get_class(starting_class) if isinstance(starting_class, str) else starting_class


def _budget(
    starting_class: StartingClass,
    level: int,
    fixed: Mapping[str, int] | None,
    minimum: Mapping[str, int] | None,
) -> tuple[dict[str, int], dict[str, int], int]:
    """Attribute bounds and the number of points left to spend above the lower bounds."""
    lo, hi = attribute_bounds(starting_class, fixed, minimum)
    total = level + LEVEL_OFFSET
    budget = total - sum(lo.values())
    if budget < 0:
        raise ValueError(
            f"Level {level} is too low: {starting_class.name} with these constraints "
            f"needs at least level {sum(lo.values()) - LEVEL_OFFSET}"
        )
    if total > sum(hi.values()):
        raise ValueError(
            f"Level {level} is too high: with these fixed attributes the maximum is "
            f"level {sum(hi.values()) - LEVEL_OFFSET}"
        )
    return lo, hi, budget


def optimize(
    weapon: Weapon,
    starting_class: StartingClass | str,
    level: int,
    *,
    upgrade: int | None = None,
    two_handing: bool = False,
    fixed: Mapping[str, int] | None = None,
    minimum: Mapping[str, int] | None = None,
) -> OptimizationResult:
    """Find the AR-maximizing allocations for a weapon, class and level.

    Args:
        weapon: The weapon, including affinity (``Regulation.get("Blood Uchigatana")``).
        starting_class: A ``StartingClass`` or class name. Its stats are the minimums.
        level: Target character level. Points = level + 79 - sum of lower bounds.
        upgrade: Weapon upgrade level (default: max).
        two_handing: Grip. Affects STR scaling and the STR requirement.
        fixed: Attributes held at an exact value, e.g. ``{"vig": 60}``.
        minimum: Attributes that must be at least a value, e.g. ``{"mnd": 20}``.

    Returns:
        The Pareto frontier of AR vs. arcane-scaling status buildup. If the weapon has
        no such status, the frontier is a single build with the maximum AR.
    """
    starting_class = _as_class(starting_class)
    upgrade = weapon.max_upgrade if upgrade is None else upgrade
    lo, hi, budget = _budget(starting_class, level, fixed, minimum)

    cases = _build_cases(weapon, upgrade, two_handing, lo, hi, budget)
    arc_range = range(0, min(hi[_ARCANE] - lo[_ARCANE], budget) + 1)

    candidates: list[Build] = []
    for z_arc in arc_range:
        best: tuple[float, int, dict[str, int]] | None = None
        for case in cases:
            h_arc = case.tables[_ARCANE][z_arc]
            if np.isneginf(h_arc):
                continue
            value = case.constant + h_arc + case.history[-1][budget - z_arc]
            if np.isneginf(value):
                continue
            extra, used = _backtrack(case, budget - z_arc)
            if (
                best is None
                or value > best[0] + TOLERANCE
                or (value >= best[0] - TOLERANCE and used < best[1])
            ):
                best = (value, used, extra)
        if best is None:
            continue
        _, used, extra = best
        attrs = dict(lo)
        for a, z in extra.items():
            attrs[a] += z
        attrs[_ARCANE] += z_arc
        rating = attack_rating(weapon, attrs, upgrade, two_handing)
        candidates.append(Build(attrs, rating, budget - used - z_arc))

    status_types = tuple(
        t for t, term in type_terms(weapon, upgrade).items()
        if t.is_status and _ARCANE in term.scaling
    )
    return OptimizationResult(
        weapon=weapon,
        upgrade=upgrade,
        two_handing=two_handing,
        starting_class=starting_class,
        level=level,
        status_types=status_types,
        frontier=tuple(_pareto(candidates, status_types)),
    )


def _pareto(builds: list[Build], status_types: tuple[AttackPowerType, ...]) -> list[Build]:
    """Drop builds another build matches or beats on AR and every status type.

    Exact ties go to the build with less arcane (more free points).
    """

    def dominates(j: Build, i: Build) -> bool:
        sj = [j.status.get(t, 0.0) for t in status_types]
        si = [i.status.get(t, 0.0) for t in status_types]
        if j.ar < i.ar - TOLERANCE or any(x < y - TOLERANCE for x, y in zip(sj, si)):
            return False
        strictly = j.ar > i.ar + TOLERANCE or any(x > y + TOLERANCE for x, y in zip(sj, si))
        return strictly or j.attributes[_ARCANE] < i.attributes[_ARCANE]

    return [b for b in builds if not any(dominates(o, b) for o in builds if o is not b)]


# ---------------------------------------------------------------------- vs. an enemy
@dataclass(frozen=True)
class EnemyBuild:
    """A build scored against an enemy."""

    build: Build
    damage: HitDamage


@dataclass(frozen=True)
class EnemyOptimizationResult:
    weapon: Weapon
    upgrade: int
    two_handing: bool
    starting_class: StartingClass
    level: int
    enemy: Enemy
    motion_value: float
    attack_type: str
    bleed_flat: float
    #: The build with the most damage per hit against the enemy.
    best: EnemyBuild
    #: The highest-AR build, scored against the same enemy, for comparison.
    highest_ar: EnemyBuild
    #: "frontier" (single damage type) or "enumeration" (split damage).
    method: str


def optimize_vs_enemy(
    weapon: Weapon,
    starting_class: StartingClass | str,
    level: int,
    enemy: Enemy,
    *,
    upgrade: int | None = None,
    two_handing: bool = False,
    fixed: Mapping[str, int] | None = None,
    minimum: Mapping[str, int] | None = None,
    motion_value: float = 100.0,
    attack_type: str = "standard",
    bleed_flat: float | None = None,
    regulation: Regulation | None = None,
    method: str = "auto",
) -> EnemyOptimizationResult:
    """Find the allocation with the most damage per hit against one enemy.

    Damage per hit is direct damage (each damage type through the enemy's defense and
    negation) plus bleed averaged over the hits it takes to proc. See ``erbuild.damage``.

    Args:
        enemy: From ``load_enemies().get(...)``.
        motion_value: The attack's motion value (100 = the weapon's full AR).
        attack_type: Physical attack type: standard, strike, slash or pierce.
        bleed_flat: Flat part of a bleed proc; defaults to 100 or 200 by weapon.
        regulation: Used to decide the bleed flat amount (default: bundled data).
        method: "auto", "frontier" or "enumeration". "auto" uses the AR frontier when
            the weapon deals one damage type, where it's exact, and enumeration otherwise.
    Other arguments are as for ``optimize``.
    """
    starting_class = _as_class(starting_class)
    upgrade = weapon.max_upgrade if upgrade is None else upgrade
    lo, hi, budget = _budget(starting_class, level, fixed, minimum)
    if attack_type not in ATTACK_TYPES:
        raise ValueError(f"attack_type must be one of {', '.join(ATTACK_TYPES)}")
    if bleed_flat is None:
        bleed_flat = bleed_flat_damage(weapon, regulation or load_default())

    def score(build: Build) -> EnemyBuild:
        values = build.rating.values
        return EnemyBuild(
            build, hit_breakdown(values, enemy, motion_value, attack_type, bleed_flat)
        )

    ar_result = optimize(
        weapon, starting_class, level,
        upgrade=upgrade, two_handing=two_handing, fixed=fixed, minimum=minimum,
    )
    terms = type_terms(weapon, upgrade)
    damage_types = [t for t in terms if t.is_damage]
    if method == "auto":
        method = "frontier" if len(damage_types) <= 1 else "enumeration"

    if method == "frontier":
        # One damage type: for a fixed arcane value, bleed is fixed and damage rises
        # with AR, so the best build against any enemy is on the AR frontier.
        scored = [score(b) for b in ar_result.frontier]
        top = max(s.damage.total for s in scored)
        best = next(s for s in scored if s.damage.total >= top - TOLERANCE)
    elif method == "enumeration":
        def objective(values):
            return damage_per_hit(values, enemy, motion_value, attack_type, bleed_flat)

        bleed_matters = (
            AttackPowerType.BLEED in terms
            and enemy.resistance.get(AttackPowerType.BLEED) is not None
        )
        relevant = {a for t in damage_types for a in (*terms[t].scaling, *terms[t].requires)}
        if bleed_matters:
            bleed = terms[AttackPowerType.BLEED]
            relevant |= {*bleed.scaling, *bleed.requires}
        stats = [a for a in SCALING_ATTRIBUTES if a in relevant]
        extra = _enumerate(weapon, upgrade, two_handing, lo, hi, budget, stats, objective)
        attrs = dict(lo)
        for a, z in extra.items():
            attrs[a] += z
        rating = attack_rating(weapon, attrs, upgrade, two_handing)
        best = score(Build(attrs, rating, budget - sum(extra.values())))
    else:
        raise ValueError("method must be 'auto', 'frontier' or 'enumeration'")

    return EnemyOptimizationResult(
        weapon=weapon,
        upgrade=upgrade,
        two_handing=two_handing,
        starting_class=starting_class,
        level=level,
        enemy=enemy,
        motion_value=motion_value,
        attack_type=attack_type,
        bleed_flat=bleed_flat,
        best=best,
        highest_ar=score(ar_result.best),
        method=method,
    )


def _enumerate(weapon, upgrade, two_handing, lo, hi, budget, stats, objective) -> dict[str, int]:
    """Exhaustive search over allocations of `stats` that spend the whole usable budget.

    The objective never decreases when a point is added, so some optimum spends
    S = min(budget, room left in `stats`). Points that don't help are then trimmed back
    (they become free points). Returns extra points per stat above its lower bound.
    """
    if not stats:
        return {}
    caps = [min(hi[a] - lo[a], budget) for a in stats]
    spend = min(budget, sum(caps))

    def evaluate(grid: np.ndarray) -> np.ndarray:
        attrs = {a: lo[a] for a in SCALING_ATTRIBUTES}
        for a, row in zip(stats, grid):
            attrs[a] = lo[a] + row
        values = attack_power(weapon, attrs, upgrade, two_handing)
        return np.broadcast_to(objective(values), grid.shape[1:])

    best_value, best_z = -np.inf, None
    # Loop over the first stat; enumerate the middle stats; the last takes the rest.
    for first in range(min(caps[0], spend) + 1):
        middle = [np.arange(min(c, spend - first) + 1) for c in caps[1:-1]]
        if len(stats) == 1:
            if first != spend:
                continue
            grid = np.array([[first]])
        else:
            if middle:
                mesh = np.array(np.meshgrid(*middle, indexing="ij")).reshape(len(middle), -1)
            else:
                mesh = np.zeros((0, 1), dtype=np.int64)
            last = spend - first - mesh.sum(axis=0)
            ok = (last >= 0) & (last <= caps[-1])
            if not ok.any():
                continue
            grid = np.vstack([np.full((1, ok.sum()), first), mesh[:, ok], last[None, ok]])
        values = evaluate(grid)
        i = int(np.argmax(values))
        if values[i] > best_value + TOLERANCE:
            best_value, best_z = float(values[i]), grid[:, i].copy()

    # Trim points that don't change the objective, so they show up as free points.
    z = best_z.copy()
    changed = True
    while changed:
        changed = False
        for k in range(len(stats)):
            if z[k] == 0:
                continue
            trial = z.copy()
            trial[k] -= 1
            if float(evaluate(trial[:, None])[0]) >= best_value - TOLERANCE:
                z, changed = trial, True
    return {a: int(v) for a, v in zip(stats, z)}
