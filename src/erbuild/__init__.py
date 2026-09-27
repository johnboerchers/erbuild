"""erbuild: Elden Ring attack rating calculator and stat allocation optimizer."""

from .calculator import AttackRating, attack_power, attack_rating
from .classes import STARTING_CLASSES, StartingClass, get_class
from .constants import AttackPowerType
from .damage import damage_per_hit, hit_breakdown
from .enemies import Enemy, load_enemies, update_enemy_data
from .optimizer import Build, EnemyOptimizationResult, OptimizationResult, optimize, optimize_vs_enemy
from .regulation import Regulation, Weapon, load_default

__all__ = [
    "AttackPowerType",
    "AttackRating",
    "Build",
    "Enemy",
    "EnemyOptimizationResult",
    "OptimizationResult",
    "Regulation",
    "STARTING_CLASSES",
    "StartingClass",
    "Weapon",
    "attack_power",
    "attack_rating",
    "damage_per_hit",
    "get_class",
    "hit_breakdown",
    "load_default",
    "load_enemies",
    "optimize",
    "optimize_vs_enemy",
    "update_enemy_data",
]

__version__ = "1.0.0"
