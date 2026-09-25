"""Enemy stats: HP, defense, damage negation and status resistances.

The data comes from the community "Elden Ring PvE Enemy Health / Defense Data" Google
Sheet, which is derived from the game's regulation params with each placement's area
scaling applied. The sheet has no stated license, so erbuild never bundles it:
``erbuild enemies update`` downloads it on your machine and converts it to a local
JSON cache.

The workbook is read with the standard library (an .xlsx file is zipped XML), because
the sheet's CSV export silently drops text like "Immune" from numeric columns.
"""

from __future__ import annotations

import difflib
import json
import os
import re
import tempfile
import urllib.request
import zipfile
from dataclasses import dataclass
from datetime import date
from functools import lru_cache
from pathlib import Path
from xml.etree import ElementTree

from .constants import AttackPowerType

SHEET_ID = "1BVwmKqB8pvuyJkSTGYOM2kAJxFMQ0jVsc6aKYz_Upes"
SHEET_URL = f"https://docs.google.com/spreadsheets/d/{SHEET_ID}/edit"
DOWNLOAD_URL = f"https://docs.google.com/spreadsheets/d/{SHEET_ID}/export?format=xlsx"

#: Journey cycles, in the order of the sheet's tabs.
CYCLE_SHEETS = ("NG", "NG+", "NG+2", "NG+3", "NG+4", "NG+5", "NG+6", "NG+7")

#: Physical attack types. Enemies have a separate defense and negation for each.
ATTACK_TYPES = ("standard", "strike", "slash", "pierce")

#: Defense / negation columns in the sheet -> our keys.
_TYPE_COLUMNS = {
    "Phys": "standard", "Strike": "strike", "Slash": "slash", "Pierce": "pierce",
    "Magic": "magic", "Fire": "fire", "Ltng": "lightning", "Holy": "holy",
}
_RESISTANCE_COLUMNS = {
    "Poison": AttackPowerType.POISON, "Scarlet Rot": AttackPowerType.SCARLET_ROT,
    "Bleed": AttackPowerType.BLEED, "Frost": AttackPowerType.FROST,
    "Sleep": AttackPowerType.SLEEP, "Madness": AttackPowerType.MADNESS,
    "Deathblight": AttackPowerType.DEATH_BLIGHT,
}
_STATUS_MULTIPLIER_COLUMNS = {
    "Bleed": AttackPowerType.BLEED, "Frost": AttackPowerType.FROST,
    "Sleep": AttackPowerType.SLEEP, "Madness": AttackPowerType.MADNESS,
}

#: Damage type of each AttackPowerType, as used for defense and negation lookups.
DAMAGE_TYPE_KEYS = {
    AttackPowerType.MAGIC: "magic", AttackPowerType.FIRE: "fire",
    AttackPowerType.LIGHTNING: "lightning", AttackPowerType.HOLY: "holy",
}


@dataclass(frozen=True)
class Enemy:
    """One enemy placement in one journey cycle."""

    name: str
    location: str
    cycle: int
    npc_id: str
    hp: float
    #: Flat defense per type: standard/strike/slash/pierce/magic/fire/lightning/holy.
    defense: dict[str, float]
    #: Damage negation per type, in percent (can be negative: a weakness).
    negation: dict[str, float]
    #: Buildup needed to trigger each status; None means immune.
    resistance: dict[AttackPowerType, float | None]
    #: Multiplier on status effect damage taken (e.g. 0.7 bleed for most bosses).
    status_multiplier: dict[AttackPowerType, float]

    @property
    def is_boss(self) -> bool:
        return "[Boss]" in self.name

    @property
    def cycle_name(self) -> str:
        return CYCLE_SHEETS[self.cycle]

    def same_stats(self, other: Enemy) -> bool:
        return (self.hp, self.defense, self.negation, self.resistance, self.status_multiplier) == (
            other.hp, other.defense, other.negation, other.resistance, other.status_multiplier
        )


def parse_cycle(value: str | int) -> int:
    """Accept 0..7, "ng", "ng+", "ng+3", "NG+ 3"."""
    if isinstance(value, int):
        cycle = value
    else:
        text = value.strip().lower().replace(" ", "")
        match = re.fullmatch(r"(?:ng)?(\+)?(\d*)", text)
        if not match or text == "":
            raise ValueError(f"Unknown cycle {value!r}: use ng, ng+, ng+2 … ng+7")
        plus, digits = match.groups()
        if digits:
            cycle = int(digits)
        else:
            cycle = 1 if plus else 0
    if not 0 <= cycle < len(CYCLE_SHEETS):
        raise ValueError(f"Cycle must be between NG and NG+7, got {value!r}")
    return cycle


# ---------------------------------------------------------------------- cache
def default_cache_path() -> Path:
    base = os.environ.get("ERBUILD_CACHE") or os.environ.get("XDG_CACHE_HOME")
    root = Path(base) if base else Path.home() / ".cache"
    if not os.environ.get("ERBUILD_CACHE"):
        root = root / "erbuild"
    return root / "enemies.json"


def update_enemy_data(path: str | Path | None = None, url: str = DOWNLOAD_URL) -> Path:
    """Download the enemy sheet and write the JSON cache. Returns the cache path."""
    path = Path(path) if path else default_cache_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory() as tmp:
        workbook = Path(tmp) / "enemies.xlsx"
        with urllib.request.urlopen(url, timeout=120) as response:
            workbook.write_bytes(response.read())
        data = convert_workbook(workbook)
    data["retrieved"] = date.today().isoformat()
    path.write_text(json.dumps(data, separators=(",", ":")), encoding="utf-8")
    load_enemies.cache_clear()
    return path


def convert_workbook(path: str | Path) -> dict:
    """Convert the downloaded .xlsx into the cache format."""
    sheets = read_xlsx(path, CYCLE_SHEETS)
    cycles = {}
    invulnerable: set[str] = set()
    for cycle, name in enumerate(CYCLE_SHEETS):
        if name not in sheets:
            raise ValueError(f"Enemy workbook has no {name!r} sheet; has the format changed?")
        cycles[str(cycle)], skipped = _parse_sheet(sheets[name])
        invulnerable.update(skipped)
    return {"source": SHEET_URL, "cycles": cycles, "invulnerable": sorted(invulnerable)}


def _parse_sheet(rows: list[list]) -> tuple[list[dict], list[str]]:
    groups, headers = rows[0], rows[1]
    columns: dict[tuple[str, str], int] = {}
    group = ""
    for i, header in enumerate(headers):
        if i < len(groups) and groups[i] not in (None, ""):
            group = str(groups[i])
        if header not in (None, ""):
            columns[(group, str(header))] = i

    def col(group_prefix: str, header: str) -> int:
        for (g, h), i in columns.items():
            if h == header and g.startswith(group_prefix):
                return i
        raise ValueError(f"Enemy sheet is missing column {group_prefix} / {header}")

    first = {h: i for (g, h), i in reversed(list(columns.items()))}
    location, name, npc_id, health = first["Location"], first["Name"], first["Npc_ID"], first["Health"]
    defense = {key: col("Defense", h) for h, key in _TYPE_COLUMNS.items()}
    negation = {key: col("Damage Negation", h) for h, key in _TYPE_COLUMNS.items()}
    resistance = {int(t): col("Resistances", h) for h, t in _RESISTANCE_COLUMNS.items()}
    multiplier = {int(t): col("Incoming Status", h) for h, t in _STATUS_MULTIPLIER_COLUMNS.items()}

    enemies = []
    invulnerable = set()
    for row in rows[2:]:
        cell = lambda i: row[i] if i < len(row) else None  # noqa: E731
        hp = _number(cell(health))
        # 0 HP marks things that can't be damaged (e.g. the Merciless Chariot).
        if cell(name) and hp is not None and hp <= 0:
            invulnerable.add(str(cell(name)).strip())
        if not cell(name) or hp is None or hp <= 0:
            continue
        defenses = {k: _number(cell(i)) for k, i in defense.items()}
        negations = {k: _number(cell(i)) for k, i in negation.items()}
        if any(v is None for v in (*defenses.values(), *negations.values())):
            continue
        enemies.append({
            "name": str(cell(name)).strip(),
            "location": str(cell(location) or "").strip(),
            "npc_id": _id(cell(npc_id)),
            "hp": hp,
            "defense": defenses,
            "negation": negations,
            "resistance": {str(t): _number(cell(i)) for t, i in resistance.items()},
            "status_multiplier": {str(t): _number(cell(i), 1.0) for t, i in multiplier.items()},
        })
    names = {e["name"] for e in enemies}
    return enemies, sorted(invulnerable - names)


def _number(value, default=None):
    if value is None:
        return default
    if isinstance(value, (int, float)):
        return float(value)
    text = str(value).strip().replace(",", "")
    try:
        return float(text)
    except ValueError:
        return default  # "Immune", "-", ""


def _id(value) -> str:
    if isinstance(value, float) and value.is_integer():
        return str(int(value))
    return str(value or "")


# ---------------------------------------------------------------------- xlsx reader
_NS = {"m": "http://schemas.openxmlformats.org/spreadsheetml/2006/main"}
_REL = "{http://schemas.openxmlformats.org/officeDocument/2006/relationships}id"


def read_xlsx(path: str | Path, sheet_names: tuple[str, ...] | None = None) -> dict[str, list[list]]:
    """Minimal .xlsx reader: cell values (strings and numbers) for the named sheets."""
    with zipfile.ZipFile(path) as z:
        strings = []
        if "xl/sharedStrings.xml" in z.namelist():
            root = ElementTree.fromstring(z.read("xl/sharedStrings.xml"))
            for si in root.findall("m:si", _NS):
                strings.append("".join(t.text or "" for t in si.iter(f"{{{_NS['m']}}}t")))

        workbook = ElementTree.fromstring(z.read("xl/workbook.xml"))
        rels = ElementTree.fromstring(z.read("xl/_rels/workbook.xml.rels"))
        targets = {r.get("Id"): r.get("Target") for r in rels}

        out = {}
        for sheet in workbook.find("m:sheets", _NS):
            name = sheet.get("name")
            if sheet_names is not None and name not in sheet_names:
                continue
            target = targets[sheet.get(_REL)].lstrip("/")
            target = target if target.startswith("xl/") else f"xl/{target}"
            out[name] = _read_sheet(z.read(target), strings)
        return out


def _read_sheet(xml: bytes, strings: list[str]) -> list[list]:
    rows: list[list] = []
    for row in ElementTree.fromstring(xml).iter(f"{{{_NS['m']}}}row"):
        # Writers may skip empty rows; the r attribute (1-based) says where this one goes.
        number = row.get("r")
        if number and number.isdigit():
            rows.extend([] for _ in range(int(number) - 1 - len(rows)))
        values: list = []
        for c in row.findall("m:c", _NS):
            ref = c.get("r")
            index = _column_index(ref) if ref else len(values)
            kind = c.get("t")
            if kind == "inlineStr":
                value = "".join(t.text or "" for t in c.iter(f"{{{_NS['m']}}}t"))
            else:
                v = c.find("m:v", _NS)
                if v is None or v.text is None:
                    continue
                if kind == "s":
                    value = strings[int(v.text)]
                elif kind in ("str", "e"):
                    value = v.text
                elif kind == "b":
                    value = v.text == "1"
                else:
                    value = float(v.text)
            values.extend([None] * (index + 1 - len(values)))
            values[index] = value
        rows.append(values)
    return rows


def _column_index(ref: str) -> int:
    index = 0
    for ch in ref:
        if not ch.isalpha():
            break
        index = index * 26 + (ord(ch.upper()) - 64)
    return index - 1


# ---------------------------------------------------------------------- lookup
class EnemyData:
    """All enemy placements, for every journey cycle."""

    def __init__(self, raw: dict) -> None:
        self.source = raw.get("source", SHEET_URL)
        self.retrieved = raw.get("retrieved")
        self.enemies: dict[int, list[Enemy]] = {}
        #: Names that only appear with 0 HP: they can't be damaged, so they're left out.
        self.invulnerable = {n.lower() for n in raw.get("invulnerable", [])}
        for cycle, rows in raw["cycles"].items():
            self.enemies[int(cycle)] = [_decode(row, int(cycle)) for row in rows if row["hp"] > 0]
            self.invulnerable.update(row["name"].lower() for row in rows if row["hp"] <= 0)
        self.invulnerable -= {e.name.lower() for e in self.enemies.get(0, [])}

    def __len__(self) -> int:
        return len(self.enemies.get(0, []))

    def search(self, query: str, cycle: int = 0, limit: int = 20) -> list[Enemy]:
        q = query.strip().lower()
        hits = [e for e in self.enemies[cycle] if q in e.name.lower()]
        hits.sort(key=lambda e: (not e.is_boss, len(e.name), e.name, e.location))
        return hits[: max(0, limit)]

    def get(
        self, name: str, cycle: int = 0, location: str | None = None, variant: int | None = None
    ) -> Enemy:
        """Look up an enemy by name (case-insensitive).

        Some names have several placements with different stats. `location` (a
        case-insensitive substring) narrows them down; when placements in the same
        location still differ, `variant` picks one by number (1, 2, …) in the order the
        error message lists them.
        """
        if not name or not name.strip():
            raise KeyError("Enter an enemy name.")
        pool = self.enemies[cycle]
        matches = [e for e in pool if e.name.lower() == name.strip().lower()]
        if not matches and name.strip().lower() in self.invulnerable:
            raise KeyError(f"{name.strip()} can't be damaged (the enemy data lists 0 HP), "
                           "so there's nothing to optimize against.")
        if not matches:
            names = sorted({e.name for e in pool})
            lowered = {n.lower(): n for n in names}
            close = difflib.get_close_matches(name.lower(), lowered, n=5, cutoff=0.5)
            contains = sorted((n for n in names if name.lower() in n.lower()), key=len)[:5]
            options = list(dict.fromkeys(contains + [lowered[c] for c in close]))[:6]
            hint = f" Did you mean: {'; '.join(options)}?" if options else ""
            raise KeyError(f"No enemy named {name!r}.{hint}")
        if location:
            located = [e for e in matches if location.lower() in e.location.lower()]
            if not located:
                places = "; ".join(sorted({e.location for e in matches}))
                raise KeyError(f"{matches[0].name} isn't found at {location!r}. Locations: {places}")
            matches = located

        # Placements with identical stats are interchangeable; keep one of each.
        variants: list[Enemy] = []
        for e in matches:
            if not any(e.same_stats(v) for v in variants):
                variants.append(e)
        if variant is not None:
            if not 1 <= variant <= len(variants):
                raise KeyError(
                    f"{matches[0].name} has {len(variants)} variant(s) here; "
                    f"pick a number from 1 to {len(variants)}."
                )
            return variants[variant - 1]
        if len(variants) == 1:
            return variants[0]
        listed = [f"{i}: {v.location} ({v.hp:,.0f} HP)" for i, v in enumerate(variants[:12], 1)]
        if len(variants) > 12:
            listed.append(f"… {len(variants) - 12} more")
        raise KeyError(
            f"{matches[0].name} has {len(variants)} placements with different stats. "
            f"Narrow it down with a location, or pick a variant number: {'; '.join(listed)}"
        )


def _decode(row: dict, cycle: int) -> Enemy:
    return Enemy(
        name=row["name"],
        location=row["location"],
        cycle=cycle,
        npc_id=row["npc_id"],
        hp=row["hp"],
        defense=row["defense"],
        negation=row["negation"],
        resistance={AttackPowerType(int(t)): v for t, v in row["resistance"].items()},
        status_multiplier={AttackPowerType(int(t)): v for t, v in row["status_multiplier"].items()},
    )


@lru_cache(maxsize=4)
def load_enemies(path: str | Path | None = None) -> EnemyData:
    """Load the enemy cache written by ``erbuild enemies update``."""
    path = Path(path) if path else default_cache_path()
    if not path.exists():
        raise FileNotFoundError(
            f"No enemy data at {path}. Run `erbuild enemies update` to download it "
            f"(source: {SHEET_URL})."
        )
    try:
        return EnemyData(json.loads(path.read_text(encoding="utf-8")))
    except (ValueError, KeyError, TypeError) as e:
        raise ValueError(
            f"The enemy data at {path} is unreadable ({e}). "
            "Run `erbuild enemies update` to download it again."
        ) from None
