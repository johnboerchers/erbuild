"""Load datamined regulation data and decode it into Weapon objects.

The bundled JSON is the compact format produced by Tom Clark's
elden-ring-weapon-calculator (MIT), extracted from the game's regulation.bin. It
contains the relevant rows from these params:

- ``CalcCorrectGraph``: the piecewise "soft cap" curves g_c(stat)
- ``AttackElementCorrectParam``: which attributes affect which damage type
- ``ReinforceParamWeapon``: per-upgrade-level multipliers on base attack and scaling
- ``SpEffectParam``: status buildup per upgrade level
- ``EquipParamWeapon``: per-weapon base attack, scaling, requirements
"""

from __future__ import annotations

import difflib
import json
from dataclasses import dataclass, field
from functools import lru_cache
from importlib import resources
from pathlib import Path
from typing import Union

import numpy as np

from .constants import (
    AFFINITIES,
    DAMAGE_TYPES,
    MAX_EFFECTIVE_ATTRIBUTE,
    STATUS_TYPES,
    WEAPON_TYPES,
    AttackPowerType,
)

DEFAULT_DAMAGE_GRAPH_ID = 0
DEFAULT_STATUS_GRAPH_ID = 6
DEFAULT_VERSION = "vanilla-v1.17"

#: Attribute correction entry: True means "use the weapon's scaling", a number is an override.
AttributeCorrect = Union[bool, float]


def evaluate_calc_correct_graph(stages: list[dict]) -> np.ndarray:
    """Tabulate a CalcCorrectGraph as an array indexed by attribute value (0..148).

    Each stage i spans (maxVal[i-1], maxVal[i]] and interpolates from maxGrowVal[i-1]
    to maxGrowVal[i] with an exponent taken from the *previous* stage's adjPt:

        ratio = (x - x_prev) / (x_i - x_prev)
        adjPt > 0:  ratio ** adjPt
        adjPt < 0:  1 - (1 - ratio) ** -adjPt
        g(x) = y_prev + (y_i - y_prev) * ratio
    """
    out = np.zeros(MAX_EFFECTIVE_ATTRIBUTE + 1, dtype=np.float64)
    filled = np.zeros_like(out, dtype=bool)
    for i in range(1, len(stages)):
        prev, stage = stages[i - 1], stages[i]
        lo = 1 if i == 1 else prev["maxVal"] + 1
        hi = MAX_EFFECTIVE_ATTRIBUTE if i == len(stages) - 1 else stage["maxVal"]
        for x in range(int(lo), int(hi) + 1):
            if filled[x]:
                continue
            ratio = (x - prev["maxVal"]) / (stage["maxVal"] - prev["maxVal"])
            ratio = max(0.0, min(1.0, ratio))
            adj = prev["adjPt"]
            if adj > 0:
                ratio = ratio**adj
            elif adj < 0:
                ratio = 1 - (1 - ratio) ** -adj
            out[x] = prev["maxGrowVal"] + (stage["maxGrowVal"] - prev["maxGrowVal"]) * ratio
            filled[x] = True
    return out


@dataclass(frozen=True, eq=False)
class Weapon:
    """A single weapon + affinity, fully decoded for every upgrade level."""

    name: str
    weapon_name: str
    affinity_id: int
    weapon_type: int
    requirements: dict[str, int]
    #: attack[u][type] = base attack power at upgrade level u (damage and status buildup).
    attack: list[dict[AttackPowerType, float]]
    #: attribute_scaling[u][attr] = scaling coefficient at upgrade level u (1.0 == 100%).
    attribute_scaling: list[dict[str, float]]
    #: attack_element_correct[type][attr] = True/override if `type` scales with `attr`.
    attack_element_correct: dict[AttackPowerType, dict[str, AttributeCorrect]]
    #: curves[type] = tabulated CalcCorrectGraph for that attack power type.
    curves: dict[AttackPowerType, np.ndarray] = field(repr=False)
    paired: bool = False
    sorcery_tool: bool = False
    incantation_tool: bool = False
    dlc: bool = False
    variant: str | None = None

    @property
    def max_upgrade(self) -> int:
        return len(self.attack) - 1

    @property
    def is_somber(self) -> bool:
        return self.max_upgrade == 10

    @property
    def affinity(self) -> str:
        return AFFINITIES.get(self.affinity_id, f"Affinity {self.affinity_id}")

    @property
    def weapon_type_name(self) -> str:
        return WEAPON_TYPES.get(self.weapon_type, f"Type {self.weapon_type}")

    @property
    def key(self) -> str:
        return f"{self.name} ({self.variant})" if self.variant else self.name

    def scaling_grade(self, attribute: str, upgrade: int, tiers: list[tuple[float, str]]) -> str:
        value = self.attribute_scaling[upgrade].get(attribute, 0.0)
        for threshold, label in tiers:
            if value >= threshold:
                return label
        return "-"


class Regulation:
    """All weapons from one version of the game's regulation data."""

    def __init__(self, raw: dict, version: str = "custom") -> None:
        self.version = version
        self.scaling_tiers: list[tuple[float, str]] = [(t, s) for t, s in raw["scalingTiers"]]
        self._graphs = {
            int(k): evaluate_calc_correct_graph(v) for k, v in raw["calcCorrectGraphs"].items()
        }
        self._aec = {
            int(k): {AttackPowerType(int(t)): attrs for t, attrs in v.items()}
            for k, v in raw["attackElementCorrects"].items()
        }
        self._reinforce = {int(k): v for k, v in raw["reinforceTypes"].items()}
        self._status = {
            int(k): {AttackPowerType(int(t)): val for t, val in v.items()}
            for k, v in raw["statusSpEffectParams"].items()
        }
        self.weapons: dict[str, Weapon] = {}
        for encoded in raw["weapons"]:
            weapon = self._decode(encoded)
            self.weapons[weapon.key] = weapon

    # ------------------------------------------------------------------ loading
    @classmethod
    def load(cls, path: str | Path | None = None) -> Regulation:
        """Load bundled data (default) or a JSON file in the same format."""
        if path is None:
            return load_default()
        path = Path(path)
        try:
            with path.open(encoding="utf-8") as f:
                raw = json.load(f)
            return cls(raw, version=path.stem.removeprefix("regulation-"))
        except OSError as e:
            raise ValueError(f"Can't read weapon data at {path}: {e.strerror or e}") from None
        except (ValueError, KeyError, TypeError) as e:
            raise ValueError(
                f"{path} isn't erbuild weapon data (a regulation JSON file): {e}"
            ) from None

    def _decode(self, w: dict) -> Weapon:
        aec = dict(self._aec[w["attackElementCorrectId"]])
        # Status buildup isn't in AttackElementCorrectParam; in vanilla, poison, bleed,
        # madness and sleep scale with arcane, and the rest don't scale at all.
        for t in (AttackPowerType.POISON, AttackPowerType.BLEED,
                  AttackPowerType.MADNESS, AttackPowerType.SLEEP):
            aec[t] = {"arc": True}

        graph_ids = {int(k): v for k, v in (w.get("calcCorrectGraphIds") or {}).items()}
        curves = {
            t: self._graphs[graph_ids.get(int(t), DEFAULT_DAMAGE_GRAPH_ID)] for t in DAMAGE_TYPES
        }
        curves.update(
            {t: self._graphs[graph_ids.get(int(t), DEFAULT_STATUS_GRAPH_ID)] for t in STATUS_TYPES}
        )

        reinforce = self._reinforce[w["reinforceTypeId"]]
        base_attack = [(AttackPowerType(t), v) for t, v in w["attack"]]
        base_scaling = list(w["attributeScaling"])
        status_ids = w.get("statusSpEffectParamIds") or []

        attack: list[dict[AttackPowerType, float]] = []
        scaling: list[dict[str, float]] = []
        for rp in reinforce:
            level_attack = {t: v * rp["attack"].get(str(int(t)), 0) for t, v in base_attack}
            offsets = [rp.get(f"statusSpEffectId{i}") for i in (1, 2, 3)]
            for i, sp_id in enumerate(status_ids):
                if sp_id:
                    level_attack.update(self._status.get(sp_id + (offsets[i] or 0), {}))
            attack.append(level_attack)
            scaling.append({a: v * rp["attributeScaling"][a] for a, v in base_scaling})

        return Weapon(
            name=w["name"],
            weapon_name=w["weaponName"],
            affinity_id=w["affinityId"],
            weapon_type=w["weaponType"],
            requirements=dict(w["requirements"]),
            attack=attack,
            attribute_scaling=scaling,
            attack_element_correct=aec,
            curves=curves,
            paired=w.get("paired", False),
            sorcery_tool=w.get("sorceryTool", False),
            incantation_tool=w.get("incantationTool", False),
            dlc=w.get("dlc", False),
            variant=w.get("variant"),
        )

    # ------------------------------------------------------------------ lookup
    def __len__(self) -> int:
        return len(self.weapons)

    def __iter__(self):
        return iter(self.weapons.values())

    def get(self, name: str) -> Weapon:
        """Look up a weapon by exact name (case-insensitive), with suggestions on failure."""
        if not name or not name.strip():
            raise KeyError("Enter a weapon name.")
        name = name.strip()
        if name in self.weapons:
            return self.weapons[name]
        lowered = {k.lower(): v for k, v in self.weapons.items()}
        if name.lower() in lowered:
            return lowered[name.lower()]
        suggestions = difflib.get_close_matches(name.lower(), lowered, n=5, cutoff=0.5)
        hint = f" Did you mean: {', '.join(lowered[s].key for s in suggestions)}?" if suggestions else ""
        raise KeyError(f"No weapon named {name!r}.{hint}")

    def search(self, query: str, limit: int = 20) -> list[Weapon]:
        """Case-insensitive substring search over weapon names."""
        q = query.strip().lower()
        hits = [w for w in self.weapons.values() if q in w.key.lower()]
        return sorted(hits, key=lambda w: (len(w.key), w.key))[: max(0, limit)]


@lru_cache(maxsize=1)
def load_default() -> Regulation:
    """Load the bundled regulation data (cached)."""
    ref = resources.files("erbuild") / "data" / f"regulation-{DEFAULT_VERSION}.json"
    with ref.open(encoding="utf-8") as f:
        return Regulation(json.load(f), version=DEFAULT_VERSION)
