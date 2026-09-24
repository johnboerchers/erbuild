"""erbuild: Elden Ring attack rating calculator and stat allocation optimizer."""

from .calculator import AttackRating, attack_power, attack_rating
from .classes import STARTING_CLASSES, StartingClass, get_class
from .constants import AttackPowerType
from .regulation import Regulation, Weapon, load_default

__all__ = [
    "AttackPowerType",
    "AttackRating",
    "Regulation",
    "STARTING_CLASSES",
    "StartingClass",
    "Weapon",
    "attack_power",
    "attack_rating",
    "get_class",
    "load_default",
]

__version__ = "0.1.0"
