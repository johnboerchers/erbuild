"""Game constants: attributes, attack power types, affinities and weapon types."""

from __future__ import annotations

from enum import IntEnum

#: The five attributes that weapons can scale with, in in-game menu order.
SCALING_ATTRIBUTES: tuple[str, ...] = ("str", "dex", "int", "fai", "arc")

#: All eight character attributes, in in-game menu order.
ALL_ATTRIBUTES: tuple[str, ...] = ("vig", "mnd", "end", "str", "dex", "int", "fai", "arc")

#: Level = sum(all eight attributes) - LEVEL_OFFSET, for every starting class.
LEVEL_OFFSET = 79

#: Maximum value of a single attribute.
MAX_ATTRIBUTE = 99

#: Highest effective attribute value (99 STR two-handed -> floor(1.5 * 99) = 148).
MAX_EFFECTIVE_ATTRIBUTE = 148


class AttackPowerType(IntEnum):
    """Attack power types, using the same integer ids as the regulation data."""

    PHYSICAL = 0
    MAGIC = 1
    FIRE = 2
    LIGHTNING = 3
    HOLY = 4
    POISON = 5
    SCARLET_ROT = 6
    BLEED = 7
    FROST = 8
    SLEEP = 9
    MADNESS = 10
    DEATH_BLIGHT = 11

    @property
    def is_damage(self) -> bool:
        return self <= AttackPowerType.HOLY

    @property
    def is_status(self) -> bool:
        return not self.is_damage

    @property
    def label(self) -> str:
        return self.name.replace("_", " ").title()


DAMAGE_TYPES: tuple[AttackPowerType, ...] = tuple(t for t in AttackPowerType if t.is_damage)
STATUS_TYPES: tuple[AttackPowerType, ...] = tuple(t for t in AttackPowerType if t.is_status)

#: Affinity ids used in the regulation data. -1 marks unique (non-infusable) weapons.
AFFINITIES: dict[int, str] = {
    -1: "Unique",
    0: "Standard",
    1: "Heavy",
    2: "Keen",
    3: "Quality",
    4: "Fire",
    5: "Flame Art",
    6: "Lightning",
    7: "Sacred",
    8: "Magic",
    9: "Cold",
    10: "Poison",
    11: "Blood",
    12: "Occult",
}

#: Weapon type ids used in the regulation data.
WEAPON_TYPES: dict[int, str] = {
    1: "Dagger",
    3: "Straight Sword",
    5: "Greatsword",
    7: "Colossal Sword",
    9: "Curved Sword",
    11: "Curved Greatsword",
    13: "Katana",
    14: "Twinblade",
    15: "Thrusting Sword",
    16: "Heavy Thrusting Sword",
    17: "Axe",
    19: "Greataxe",
    21: "Hammer",
    23: "Great Hammer",
    24: "Flail",
    25: "Spear",
    28: "Great Spear",
    29: "Halberd",
    31: "Reaper",
    35: "Fist",
    37: "Claw",
    39: "Whip",
    41: "Colossal Weapon",
    50: "Light Bow",
    51: "Bow",
    53: "Greatbow",
    55: "Crossbow",
    56: "Ballista",
    57: "Glintstone Staff",
    59: "Dual Catalyst",
    61: "Sacred Seal",
    65: "Small Shield",
    67: "Medium Shield",
    69: "Greatshield",
    87: "Torch",
    88: "Hand-to-Hand Art",
    89: "Perfume Bottle",
    90: "Thrusting Shield",
    91: "Throwing Blade",
    92: "Backhand Blade",
    93: "Light Greatsword",
    94: "Great Katana",
    95: "Beast Claw",
}

#: Weapon types that are always two-handed (and so always get the STR bonus).
ALWAYS_TWO_HANDED_TYPES = frozenset({50, 51, 53, 56})
