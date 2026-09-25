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
    "attack_rating", "call", "classes", "enemies", "enemy_names", "export_enemy_data",
    "load_enemy_data", "load_enemy_workbook", "optimize", "weapons",
]

#: Enemy data loaded in this process: from a downloaded workbook (the web page) or
#: from the local cache written by ``erbuild enemies update``.
_enemy_data: EnemyData | None = None
#: The converted data behind `_enemy_data`, so a UI can cache it (see export_enemy_data).
_enemy_raw: dict | None = None


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


# ---------------------------------------------------------------------- input checks
# UIs send whatever their form fields hold, so every value is checked here: numbers
# must be whole where the game needs whole numbers, booleans must really be booleans
# (the string "false" is truthy in Python), and names must be non-empty strings.
def _int(value, name: str) -> int:
    if isinstance(value, bool):
        raise ValueError(f"{name} must be a whole number, got {value!r}")
    if isinstance(value, str):
        value = value.strip()
        try:
            return int(value)
        except ValueError:
            raise ValueError(f"{name} must be a whole number, got {value!r}") from None
    if isinstance(value, int):
        return value
    if isinstance(value, float) and value.is_integer():
        return int(value)
    raise ValueError(f"{name} must be a whole number, got {value!r}")


def _optional_int(value, name: str) -> int | None:
    return None if value is None or value == "" else _int(value, name)


def _float(value, name: str) -> float:
    if isinstance(value, bool) or value is None:
        raise ValueError(f"{name} must be a number, got {value!r}")
    try:
        return float(value)
    except (TypeError, ValueError):
        raise ValueError(f"{name} must be a number, got {value!r}") from None


def _bool(value, name: str) -> bool:
    if isinstance(value, bool):
        return value
    if isinstance(value, str) and value.strip().lower() in ("true", "false", "1", "0"):
        return value.strip().lower() in ("true", "1")
    if isinstance(value, int) and value in (0, 1):
        return bool(value)
    raise ValueError(f"{name} must be true or false, got {value!r}")


def _str(value, name: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{name} must be a non-empty string")
    return value


def _stat_map(values, name: str) -> dict[str, int]:
    """{attribute: whole number}; unknown attributes are reported, not ignored."""
    if values is None:
        return {}
    if not isinstance(values, Mapping):
        raise ValueError(f"{name} must be an object like {{\"vig\": 40}}")
    out = {}
    for a, v in values.items():
        if v is None or v == "":
            continue  # an empty form field means "not set"
        out[str(a).strip().lower()] = _int(v, f"{name}.{a}")
    unknown = sorted(set(out) - set(ALL_ATTRIBUTES))
    if unknown:
        raise ValueError(f"Unknown attribute {unknown[0]!r}. Options: {', '.join(ALL_ATTRIBUTES)}")
    return out


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
    if hasattr(data, "to_bytes"):  # a JavaScript Uint8Array passed in from Pyodide
        data = data.to_bytes()
    return _set_enemy_data(convert_workbook(io.BytesIO(bytes(data))))


@_endpoint
def load_enemy_data(text: str) -> dict:
    """Load enemy data previously saved with :func:`export_enemy_data`."""
    return _set_enemy_data(json.loads(text))


def export_enemy_data() -> str:
    """The loaded enemy data as JSON, for a UI to cache locally ("" if none loaded)."""
    return json.dumps(_enemy_raw, separators=(",", ":")) if _enemy_raw else ""


def _set_enemy_data(raw: dict) -> dict:
    global _enemy_data, _enemy_raw
    _enemy_data, _enemy_raw = EnemyData(raw), raw
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
def enemies(query: str = "", cycle: str | int = "ng", limit: int = 20) -> list[dict]:
    query = query if isinstance(query, str) else ""
    limit = max(1, _int(limit, "limit"))
    return [_enemy(e) for e in _enemies().search(query, _cycle(cycle), limit)]


def _cycle(value) -> int:
    return parse_cycle("ng" if value is None or value == "" else value)


def _find_enemy(spec: Mapping) -> Enemy:
    if not isinstance(spec, Mapping):
        raise ValueError('enemy must be an object like {"name": "…", "cycle": "ng"}')
    location = spec.get("location")
    return _enemies().get(
        _str(spec.get("name"), "enemy.name"),
        _cycle(spec.get("cycle")),
        location if isinstance(location, str) and location.strip() else None,
        _optional_int(spec.get("variant"), "enemy.variant"),
    )


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
    w = reg.get(_str(weapon, "weapon"))
    upgrade = _optional_int(upgrade, "upgrade")
    upgrade = w.max_upgrade if upgrade is None else upgrade
    given = _stat_map(attributes, "attributes")
    attrs = {a: given.get(a, 10) for a in SCALING_ATTRIBUTES}
    two_handing = _bool(two_handing, "two_handing")
    motion_value = _float(motion_value, "motion_value")
    ar = _attack_rating(w, attrs, upgrade, two_handing)
    out = {
        "weapon": w.key,
        "upgrade": upgrade,
        "two_handing": two_handing,
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
        "raw_status": {_key(t): v for t, v in b.status.items()},
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
    w = reg.get(_str(weapon, "weapon"))
    starting_class = _str(starting_class, "starting_class")
    level = _int(level, "level")
    options = dict(
        upgrade=_optional_int(upgrade, "upgrade"),
        two_handing=_bool(two_handing, "two_handing"),
        fixed=_stat_map(fixed, "fixed"),
        minimum=_stat_map(minimum, "minimum"),
    )
    motion_value = _float(motion_value, "motion_value")
    if enemy:
        r = optimize_vs_enemy(
            w, starting_class, level, _find_enemy(enemy), **options,
            motion_value=motion_value, attack_type=attack_type, regulation=reg,
        )
        return {
            "weapon": w.key, "upgrade": r.upgrade, "class": r.starting_class.name,
            "class_stats": dict(r.starting_class.stats),
            "level": r.level, "enemy": _enemy(r.enemy), "method": r.method,
            "best": _enemy_build(r.best), "highest_ar": _enemy_build(r.highest_ar),
        }
    r = _optimize(w, starting_class, level, **options)
    return {
        "weapon": w.key, "upgrade": r.upgrade, "class": r.starting_class.name,
        "class_stats": dict(r.starting_class.stats),
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
