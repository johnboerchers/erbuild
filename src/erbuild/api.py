"""JSON-friendly entry points for user interfaces (the web page, bots, servers).

Every function takes and returns plain data (dicts, lists, strings, numbers), so a
UI never touches erbuild's internal types and changes inside the library don't
ripple out. Errors a user can cause (unknown weapon, level too low, …) come back as
``{"error": "message"}`` instead of raising.

From JavaScript (Pyodide), use :func:`call`, which takes and returns JSON strings::

    api.call("attack_rating", JSON.stringify({weapon: "Uchigatana", attributes: {dex: 40}}))
"""

from __future__ import annotations

import functools
import inspect
import io
import json
from collections.abc import Callable, Mapping

from .calculator import attack_rating as _attack_rating
from .classes import STARTING_CLASSES
from .constants import ALL_ATTRIBUTES, SCALING_ATTRIBUTES, AttackPowerType
from .damage import HitDamage, bleed_flat_damage, hit_breakdown
from .enemies import Enemy, EnemyData, convert_workbook, load_enemies, parse_cycle
from .optimizer import Build, EnemyBuild, optimize as _optimize, optimize_vs_enemy
from .regulation import Regulation, load_default

__all__ = [
    "attack_rating", "call", "classes", "enemies", "enemy_names", "load_enemy_workbook", "optimize", "weapons",
]

#: Enemy data loaded in this process: from a downloaded workbook (the web page) or
#: from the local cache written by ``erbuild enemies update``.
_enemy_data: EnemyData | None = None


def _endpoint(fn: Callable) -> Callable:
    @functools.wraps(fn)
    def wrapper(*args, **kwargs):
        try:
            return fn(*args, **kwargs)
        except (KeyError, ValueError, FileNotFoundError) as e:
            return {"error": str(e.args[0]) if e.args else type(e).__name__}
    return wrapper


def _regulation() -> Regulation:
    return load_default()


def _key(t: AttackPowerType) -> str:
    return t.name.lower()


# ---------------------------------------------------------------------- catalog
@_endpoint
def weapons() -> list[dict]:
    """Every weapon (one entry per affinity), for pickers and search boxes."""
    return [
        {
            "name": w.key,
            "weapon": w.weapon_name,
            "affinity": w.affinity,
            "type": w.weapon_type_name,
            "max_upgrade": w.max_upgrade,
            "requirements": dict(w.requirements),
            "dlc": w.dlc,
        }
        for w in _regulation()
    ]


@_endpoint
def classes() -> list[dict]:
    return [{"name": c.name, "level": c.level, "stats": dict(c.stats)}
            for c in STARTING_CLASSES.values()]


# ---------------------------------------------------------------------- enemies
@_endpoint
def load_enemy_workbook(data: bytes) -> dict:
    """Load enemy data from the community sheet's .xlsx bytes (downloaded by the UI)."""
    global _enemy_data
    if hasattr(data, "to_bytes"):  # a JavaScript Uint8Array passed in from Pyodide
        data = data.to_bytes()
    _enemy_data = EnemyData(convert_workbook(io.BytesIO(bytes(data))))
    return _enemy_summary()


def _enemies() -> EnemyData:
    global _enemy_data
    if _enemy_data is None:
        _enemy_data = load_enemies()
    return _enemy_data


def _enemy_summary() -> dict:
    data = _enemies()
    return {"placements": len(data), "cycles": len(data.enemies), "source": data.source}


@_endpoint
def enemy_names() -> list[str]:
    """Every distinct enemy name (same in every cycle), for pickers."""
    return sorted({e.name for e in _enemies().enemies[0]})


@_endpoint
def enemies(query: str, cycle: str | int = "ng", limit: int = 20) -> list[dict]:
    return [_enemy(e) for e in _enemies().search(query, parse_cycle(cycle), limit)]


def _find_enemy(spec: Mapping) -> Enemy:
    return _enemies().get(spec["name"], parse_cycle(spec.get("cycle", "ng")), spec.get("location"))


def _enemy(e: Enemy) -> dict:
    return {
        "name": e.name,
        "location": e.location,
        "cycle": e.cycle_name,
        "boss": e.is_boss,
        "hp": e.hp,
        "defense": dict(e.defense),
        "negation": dict(e.negation),
        "resistance": {_key(t): r for t, r in e.resistance.items()},
        "status_multiplier": {_key(t): m for t, m in e.status_multiplier.items()},
    }


def _damage(d: HitDamage) -> dict:
    return {
        "total": d.total,
        "direct": d.direct,
        "bleed_per_hit": d.bleed_per_hit,
        "bleed_proc": d.bleed_proc,
        "hits_to_proc": None if d.hits_to_proc == float("inf") else d.hits_to_proc,
    }


# ---------------------------------------------------------------------- AR
@_endpoint
def attack_rating(
    weapon: str,
    attributes: Mapping[str, int],
    upgrade: int | None = None,
    two_handing: bool = False,
    enemy: Mapping | None = None,
    motion_value: float = 100.0,
    attack_type: str = "standard",
) -> dict:
    """AR for one set of attributes; with `enemy` ({name, cycle?, location?}), damage too."""
    reg = _regulation()
    w = reg.get(weapon)
    upgrade = w.max_upgrade if upgrade is None else int(upgrade)
    attrs = {a: int(attributes.get(a, 10)) for a in SCALING_ATTRIBUTES}
    ar = _attack_rating(w, attrs, upgrade, bool(two_handing))
    out = {
        "weapon": w.key,
        "upgrade": upgrade,
        "two_handing": bool(two_handing),
        "attributes": attrs,
        "scaling": {
            a: w.scaling_grade(a, upgrade, reg.scaling_tiers)
            for a in SCALING_ATTRIBUTES if w.attribute_scaling[upgrade].get(a)
        },
        "unmet_requirements": list(ar.ineffective_attributes),
        "damage": {_key(t): v for t, v in ar.displayed.items() if t.is_damage},
        "status": {_key(t): v for t, v in ar.displayed.items() if t.is_status},
        "total": ar.displayed_total,
        "raw_total": ar.total,
    }
    if enemy:
        e = _find_enemy(enemy)
        damage = hit_breakdown(ar.values, e, motion_value, attack_type, bleed_flat_damage(w, reg))
        out["vs_enemy"] = {"enemy": _enemy(e), **_damage(damage)}
    return out


# ---------------------------------------------------------------------- optimizer
def _build(b: Build) -> dict:
    return {
        "attributes": dict(b.attributes),
        "free_points": b.free_points,
        "ar": b.rating.displayed_total,
        "raw_ar": b.ar,
        "status": {_key(t): v for t, v in b.rating.displayed.items() if t.is_status},
        "unmet_requirements": list(b.rating.ineffective_attributes),
    }


def _enemy_build(b: EnemyBuild) -> dict:
    return {**_build(b.build), "damage": _damage(b.damage)}


@_endpoint
def optimize(
    weapon: str,
    starting_class: str,
    level: int,
    upgrade: int | None = None,
    two_handing: bool = False,
    fixed: Mapping[str, int] | None = None,
    minimum: Mapping[str, int] | None = None,
    enemy: Mapping | None = None,
    motion_value: float = 100.0,
    attack_type: str = "standard",
) -> dict:
    """Best allocation(s). Without `enemy`: the AR vs. arcane-buildup frontier.

    With `enemy` ({name, cycle?, location?}): the build with the most damage per hit,
    plus the highest-AR build scored against the same enemy.
    """
    reg = _regulation()
    w = reg.get(weapon)
    fixed = {a: int(v) for a, v in (fixed or {}).items() if a in ALL_ATTRIBUTES}
    minimum = {a: int(v) for a, v in (minimum or {}).items() if a in ALL_ATTRIBUTES}
    options = dict(upgrade=upgrade, two_handing=bool(two_handing), fixed=fixed, minimum=minimum)
    if enemy:
        r = optimize_vs_enemy(
            w, starting_class, int(level), _find_enemy(enemy), **options,
            motion_value=motion_value, attack_type=attack_type, regulation=reg,
        )
        return {
            "weapon": w.key, "upgrade": r.upgrade, "class": r.starting_class.name,
            "level": r.level, "enemy": _enemy(r.enemy), "method": r.method,
            "best": _enemy_build(r.best), "highest_ar": _enemy_build(r.highest_ar),
        }
    r = _optimize(w, starting_class, int(level), **options)
    return {
        "weapon": w.key, "upgrade": r.upgrade, "class": r.starting_class.name,
        "level": r.level, "status_types": [_key(t) for t in r.status_types],
        "best": _build(r.best), "frontier": [_build(b) for b in r.frontier],
    }


# ---------------------------------------------------------------------- JSON bridge
_METHODS = {
    "weapons": weapons,
    "classes": classes,
    "enemies": enemies,
    "enemy_names": enemy_names,
    "attack_rating": attack_rating,
    "optimize": optimize,
}


def call(method: str, payload: str = "{}") -> str:
    """Call an endpoint by name with a JSON object of keyword arguments; returns JSON."""
    fn = _METHODS.get(method)
    if fn is None:
        return json.dumps({"error": f"Unknown method {method!r}"})
    try:
        kwargs = json.loads(payload or "{}")
        inspect.signature(fn).bind(**kwargs)
    except json.JSONDecodeError as e:
        return json.dumps({"error": f"Invalid JSON: {e}"})
    except TypeError as e:
        return json.dumps({"error": f"Bad arguments for {method}: {e}"})
    return json.dumps(fn(**kwargs))
