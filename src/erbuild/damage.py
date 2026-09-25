"""Damage against a specific enemy: defense, negation and bleed.

For each damage type, with attack ratio r = (AR * MV) / defense:

    damage_t = AR_t * MV * m(r) * (1 - negation_t)

where m is the game's piecewise defense curve (0.1 at low ratios up to 0.9 at r >= 8).
Physical damage uses the defense and negation of the attack's physical type
(standard, strike, slash or pierce).

Bleed adds its proc damage, spread over the hits needed to trigger it:

    bleed per hit = multiplier * (0.15 * max HP + flat) / ceil(resistance / buildup)

The bleed term is an average: the proc lands on the hit that fills the meter, and
dividing by the hits per cycle spreads it over that cycle.

Simplifications (see the README): the first proc's cycle length is used throughout
(the game raises the threshold after each proc), no buildup decay between hits, every
hit applies the weapon's full buildup, and poison, scarlet rot and frost add no damage.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass

import numpy as np
from numpy.typing import ArrayLike

from .constants import AttackPowerType
from .enemies import ATTACK_TYPES, DAMAGE_TYPE_KEYS, Enemy
from .regulation import Regulation, Weapon

#: Hemorrhage deals this fraction of the target's max HP, plus a flat amount.
BLEED_HP_FRACTION = 0.15
BLEED_FLAT_DEFAULT = 100.0
BLEED_FLAT_HIGH = 200.0

#: Weapons whose hemorrhage deals the higher flat amount, in any affinity.
_HIGH_FLAT_BLEED_WEAPONS = frozenset(
    {"Reduvia", "Morgott's Cursed Sword", "Varre's Bouquet", "Hoslow's Petal Whip"}
)
_BLOOD_AFFINITY = 11


def defense_multiplier(ratio: ArrayLike) -> np.ndarray:
    """The game's piecewise defense curve m(r), from 0.1 up to 0.9."""
    r = np.asarray(ratio, dtype=np.float64)
    return np.select(
        [r < 0.125, r < 1.0, r < 2.5, r < 8.0],
        [
            np.full_like(r, 0.1),
            0.1 + (r - 0.125) ** 2 / 2.552,
            0.7 - (2.5 - r) ** 2 / 7.5,
            0.9 - (8.0 - r) ** 2 / 151.25,
        ],
        default=0.9,
    )


def _type_key(t: AttackPowerType, attack_type: str) -> str:
    return attack_type if t == AttackPowerType.PHYSICAL else DAMAGE_TYPE_KEYS[t]


def direct_damage(
    values: Mapping[AttackPowerType, ArrayLike],
    enemy: Enemy,
    motion_value: float = 100.0,
    attack_type: str = "standard",
) -> np.ndarray:
    """Damage from one hit (before bleed), summed over damage types. Unrounded."""
    if attack_type not in ATTACK_TYPES:
        raise ValueError(f"attack_type must be one of {', '.join(ATTACK_TYPES)}")
    total = np.float64(0.0)
    for t, ar in values.items():
        if not t.is_damage:
            continue
        key = _type_key(t, attack_type)
        attack = np.asarray(ar, dtype=np.float64) * (motion_value / 100.0)
        defense = enemy.defense[key]
        ratio = attack / defense if defense > 0 else np.full_like(attack, np.inf)
        total = total + attack * defense_multiplier(ratio) * (1.0 - enemy.negation[key] / 100.0)
    return np.asarray(total)


def bleed_flat_damage(weapon: Weapon, regulation: Regulation | None = None) -> float:
    """Flat part of a hemorrhage proc: 200 for a few weapons, otherwise 100.

    The higher value applies to Reduvia, Morgott's Cursed Sword, Varre's Bouquet and
    Hoslow's Petal Whip in any affinity, and to weapons with innate bleed infused with
    the Blood affinity. Checking "innate bleed" needs the regulation data; without it,
    Blood affinity alone isn't treated as innate.
    """
    if weapon.weapon_name in _HIGH_FLAT_BLEED_WEAPONS:
        return BLEED_FLAT_HIGH
    if weapon.affinity_id == _BLOOD_AFFINITY and regulation is not None:
        standard = regulation.weapons.get(weapon.weapon_name)
        if standard is not None and standard.attack[0].get(AttackPowerType.BLEED, 0) > 0:
            return BLEED_FLAT_HIGH
    return BLEED_FLAT_DEFAULT


def bleed_proc_damage(enemy: Enemy, flat: float = BLEED_FLAT_DEFAULT) -> float:
    """Damage of one hemorrhage proc against this enemy."""
    multiplier = enemy.status_multiplier.get(AttackPowerType.BLEED, 1.0)
    return multiplier * (BLEED_HP_FRACTION * enemy.hp + flat)


def hits_to_proc(buildup: ArrayLike, resistance: float | None) -> np.ndarray:
    """Hits needed to fill the enemy's resistance once (inf if immune or no buildup)."""
    b = np.asarray(buildup, dtype=np.float64)
    if resistance is None:
        return np.full_like(b, np.inf)
    with np.errstate(divide="ignore"):
        # Round before ceil so float noise like 3.0000000001 doesn't cost a hit.
        return np.where(b > 0, np.ceil(np.round(resistance / np.where(b > 0, b, 1.0), 9)), np.inf)


def bleed_damage_per_hit(
    buildup: ArrayLike, enemy: Enemy, flat: float = BLEED_FLAT_DEFAULT
) -> np.ndarray:
    """Hemorrhage damage averaged over the hits it takes to proc."""
    hits = hits_to_proc(buildup, enemy.resistance.get(AttackPowerType.BLEED))
    return np.where(np.isinf(hits), 0.0, bleed_proc_damage(enemy, flat) / hits)


@dataclass(frozen=True)
class HitDamage:
    """Damage per hit against one enemy, broken down."""

    direct: float
    bleed_per_hit: float
    bleed_proc: float
    hits_to_proc: float

    @property
    def total(self) -> float:
        return self.direct + self.bleed_per_hit


def damage_per_hit(
    values: Mapping[AttackPowerType, ArrayLike],
    enemy: Enemy,
    motion_value: float = 100.0,
    attack_type: str = "standard",
    bleed_flat: float = BLEED_FLAT_DEFAULT,
) -> np.ndarray:
    """The enemy-aware objective: direct damage plus bleed per hit. Vectorized."""
    total = direct_damage(values, enemy, motion_value, attack_type)
    buildup = values.get(AttackPowerType.BLEED)
    if buildup is not None:
        total = total + bleed_damage_per_hit(buildup, enemy, bleed_flat)
    return total


def hit_breakdown(
    values: Mapping[AttackPowerType, float],
    enemy: Enemy,
    motion_value: float = 100.0,
    attack_type: str = "standard",
    bleed_flat: float = BLEED_FLAT_DEFAULT,
) -> HitDamage:
    """Damage per hit for a single build, with the bleed part separated."""
    direct = float(direct_damage(values, enemy, motion_value, attack_type))
    buildup = values.get(AttackPowerType.BLEED, 0.0)
    hits = float(hits_to_proc(buildup, enemy.resistance.get(AttackPowerType.BLEED)))
    proc = bleed_proc_damage(enemy, bleed_flat) if buildup and not np.isinf(hits) else 0.0
    return HitDamage(direct, proc / hits if proc else 0.0, proc, hits)
