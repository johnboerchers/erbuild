"""Attack rating (AR) calculation.

For each attack power type t (damage types and status buildup):

    AR_t = B_t(u) * (1 + sum_s  m_{t,s} * S_s(u) * g_t(a_s))        if requirements met
    AR_t = B_t(u) * (1 - 0.4)                                         otherwise

where B_t(u) is base attack at upgrade level u, S_s(u) the scaling coefficient for
attribute s, g_t the CalcCorrectGraph curve for type t, and m_{t,s} whether t
scales with s. "Requirements met" means every attribute that t scales with meets
the weapon's requirement (checked against effective, i.e. two-handed, STR).

Everything here accepts NumPy arrays for the attributes, so one call can evaluate
thousands of candidate stat allocations at once, which is what the optimizer uses.
Scalars work too.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass

import numpy as np
from numpy.typing import ArrayLike

from .constants import (
    ALWAYS_TWO_HANDED_TYPES,
    DAMAGE_TYPES,
    MAX_EFFECTIVE_ATTRIBUTE,
    SCALING_ATTRIBUTES,
    STATUS_TYPES,
    AttackPowerType,
)
from .regulation import Weapon

INEFFECTIVE_ATTRIBUTE_PENALTY = 0.4

#: Tiny offset so values like 299.99999999 display as 300 instead of 299.
_EPS = 1e-9


def gets_two_handing_bonus(weapon: Weapon, two_handing: bool) -> bool:
    """Paired weapons never get the STR bonus; bows and ballistae always do."""
    if weapon.weapon_type in ALWAYS_TWO_HANDED_TYPES:
        return True
    return two_handing and not weapon.paired


def effective_attributes(
    weapon: Weapon, attributes: Mapping[str, ArrayLike], two_handing: bool = False
) -> dict[str, np.ndarray]:
    """Apply the two-handing bonus: effective STR = floor(1.5 * STR)."""
    eff = {a: np.asarray(attributes.get(a, 1), dtype=np.int64) for a in SCALING_ATTRIBUTES}
    if gets_two_handing_bonus(weapon, two_handing):
        eff["str"] = np.minimum((eff["str"] * 3) // 2, MAX_EFFECTIVE_ATTRIBUTE)
    return eff


def attack_power(
    weapon: Weapon,
    attributes: Mapping[str, ArrayLike],
    upgrade: int,
    two_handing: bool = False,
    ineffective_penalty: float = INEFFECTIVE_ATTRIBUTE_PENALTY,
) -> dict[AttackPowerType, np.ndarray]:
    """Unrounded attack power per type. Attribute values may be scalars or arrays.

    Returns only the types the weapon actually has (base attack > 0 at this level).
    """
    if not 0 <= upgrade <= weapon.max_upgrade:
        raise ValueError(f"{weapon.name} upgrade level must be 0..{weapon.max_upgrade}")

    raw = {a: np.asarray(attributes.get(a, 1), dtype=np.int64) for a in SCALING_ATTRIBUTES}
    eff = effective_attributes(weapon, attributes, two_handing)
    for a in SCALING_ATTRIBUTES:
        if np.any(raw[a] < 1) or np.any(raw[a] > 99):
            raise ValueError(f"{a} must be between 1 and 99")

    # Requirement check uses effective (two-handed) attributes.
    unmet = {a: eff[a] < req for a, req in weapon.requirements.items()}

    base = weapon.attack[upgrade]
    scaling = weapon.attribute_scaling[upgrade]
    base_scaling = weapon.attribute_scaling[0]
    result: dict[AttackPowerType, np.ndarray] = {}

    for t in (*DAMAGE_TYPES, *STATUS_TYPES):
        b = base.get(t, 0.0)
        if not b:
            continue
        correct = weapon.attack_element_correct.get(t, {})
        # Two-handing only boosts damage scaling, not status buildup.
        stats = eff if t.is_damage else raw

        total = np.ones(np.broadcast_shapes(*(v.shape for v in raw.values())), dtype=np.float64)
        any_unmet = np.zeros(total.shape, dtype=bool)
        for a in SCALING_ATTRIBUTES:
            flag = correct.get(a)
            if not flag:
                continue
            if a in unmet:
                any_unmet = any_unmet | unmet[a]
            if flag is True:
                s = scaling.get(a, 0.0)
            else:  # numeric override, scaled by the upgrade growth of that attribute
                s0 = base_scaling.get(a, 0.0)
                s = flag * scaling.get(a, 0.0) / s0 if s0 else 0.0
            if s:
                total = total + weapon.curves[t][stats[a]] * s

        total = np.where(any_unmet, 1.0 - ineffective_penalty, total)
        result[t] = b * total
    return result


@dataclass(frozen=True)
class AttackRating:
    """AR for a single set of attributes, with in-game style rounding helpers."""

    weapon: Weapon
    upgrade: int
    two_handing: bool
    attributes: dict[str, int]
    values: dict[AttackPowerType, float]
    ineffective_attributes: tuple[str, ...]

    @property
    def damage(self) -> dict[AttackPowerType, float]:
        return {t: v for t, v in self.values.items() if t.is_damage}

    @property
    def status(self) -> dict[AttackPowerType, float]:
        return {t: v for t, v in self.values.items() if t.is_status}

    @property
    def total(self) -> float:
        """Unrounded total damage AR (sum over damage types)."""
        return float(sum(self.damage.values()))

    @property
    def displayed(self) -> dict[AttackPowerType, int]:
        """Per-type values truncated to integers, as the game displays them."""
        return {t: int(np.floor(v + _EPS)) for t, v in self.values.items()}

    @property
    def displayed_total(self) -> int:
        return int(np.floor(self.total + _EPS))


def attack_rating(
    weapon: Weapon,
    attributes: Mapping[str, int],
    upgrade: int | None = None,
    two_handing: bool = False,
) -> AttackRating:
    """Compute AR for one set of attributes. `upgrade` defaults to the max level."""
    upgrade = weapon.max_upgrade if upgrade is None else upgrade
    values = attack_power(weapon, attributes, upgrade, two_handing)
    eff = effective_attributes(weapon, attributes, two_handing)
    ineffective = tuple(a for a, req in weapon.requirements.items() if eff[a] < req)
    return AttackRating(
        weapon=weapon,
        upgrade=upgrade,
        two_handing=two_handing,
        attributes={a: int(attributes.get(a, 1)) for a in SCALING_ATTRIBUTES},
        values={t: float(v) for t, v in values.items()},
        ineffective_attributes=ineffective,
    )
