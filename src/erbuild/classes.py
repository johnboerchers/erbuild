"""Starting classes and their base attributes.

These are the lower bounds b_i in the optimization problem: a character can never
have less of an attribute than their starting class began with.
"""

from __future__ import annotations

from dataclasses import dataclass

from .constants import ALL_ATTRIBUTES, LEVEL_OFFSET


@dataclass(frozen=True)
class StartingClass:
    name: str
    level: int
    stats: dict[str, int]

    def __post_init__(self) -> None:
        if set(self.stats) != set(ALL_ATTRIBUTES):
            raise ValueError(f"{self.name}: stats must define exactly {ALL_ATTRIBUTES}")
        if sum(self.stats.values()) - LEVEL_OFFSET != self.level:
            raise ValueError(f"{self.name}: stats don't sum to level + {LEVEL_OFFSET}")


def _cls(name: str, level: int, *values: int) -> StartingClass:
    return StartingClass(name, level, dict(zip(ALL_ATTRIBUTES, values, strict=True)))


#: Starting classes, stats in order VIG, MND, END, STR, DEX, INT, FAI, ARC.
STARTING_CLASSES: dict[str, StartingClass] = {
    c.name.lower(): c
    for c in (
        _cls("Vagabond", 9, 15, 10, 11, 14, 13, 9, 9, 7),
        _cls("Warrior", 8, 11, 12, 11, 10, 16, 10, 8, 9),
        _cls("Hero", 7, 14, 9, 12, 16, 9, 7, 8, 11),
        _cls("Bandit", 5, 10, 11, 10, 9, 13, 9, 8, 14),
        _cls("Astrologer", 6, 9, 15, 9, 8, 12, 16, 7, 9),
        _cls("Prophet", 7, 10, 14, 8, 11, 10, 7, 16, 10),
        _cls("Samurai", 9, 12, 11, 13, 12, 15, 9, 8, 8),
        _cls("Prisoner", 9, 11, 12, 11, 11, 14, 14, 6, 9),
        _cls("Confessor", 10, 10, 13, 10, 12, 12, 9, 14, 9),
        _cls("Wretch", 1, 10, 10, 10, 10, 10, 10, 10, 10),
    )
}


def get_class(name: str) -> StartingClass:
    try:
        return STARTING_CLASSES[name.strip().lower()]
    except KeyError:
        options = ", ".join(c.name for c in STARTING_CLASSES.values())
        raise KeyError(f"Unknown class {name!r}. Options: {options}") from None
