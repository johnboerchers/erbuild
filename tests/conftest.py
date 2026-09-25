"""Shared test helpers: a synthetic enemy workbook in the community sheet's layout.

Tests never download the real enemy data; this builds a tiny .xlsx with the same
structure (two header rows, one sheet per journey cycle).
"""

import zipfile

import pytest

from erbuild.enemies import CYCLE_SHEETS

GROUPS = ["{cycle}", None, None, None, None, None, None, None, None, "Defense"] + [None] * 8 + \
    ["Damage Negation"] + [None] * 8 + ["Resistances"] + [None] * 7 + \
    ["Incoming Status Damage Multipliers"]
HEADERS = ["Location", "Name", "Npc_ID", "Chara_ID", "LookupID", None, "Health", "dlcClear", None,
           "Phys", "Strike", "Slash", "Pierce", "Magic", "Fire", "Ltng", "Holy", None,
           "Phys", "Strike", "Slash", "Pierce", "Magic", "Fire", "Ltng", "Holy", None,
           "Poison", "Scarlet Rot", "Bleed", "Frost", "Sleep", "Madness", "Deathblight", None,
           "Bleed", "Frost", "Sleep", "Madness", "HP Burn Effect"]


def _row(location, name, hp, defense, bleed, mult):
    return [location, name, 123.0, None, 123.0, None, hp, "-", None, *[defense] * 8, None,
            10.0, 0.0, -10.0, 0.0, 20.0, 0.0, 20.0, 40.0, None,
            "Immune", "Immune", bleed, 300.0, 500.0, "Immune", "Immune", None,
            mult, 0.7, 1.0, 1.0, 1.0]


def _cell(ref, value):
    if value is None:
        return ""
    if isinstance(value, str):
        return f'<c r="{ref}" t="inlineStr"><is><t>{value}</t></is></c>'
    return f'<c r="{ref}"><v>{value}</v></c>'


def _col(i):
    s = ""
    i += 1
    while i:
        i, rem = divmod(i - 1, 26)
        s = chr(65 + rem) + s
    return s


def write_workbook(path, rows_by_sheet):
    ns = 'xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main"'
    rel_ns = 'xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships"'
    with zipfile.ZipFile(path, "w") as z:
        sheets, rels = [], []
        for n, (name, rows) in enumerate(rows_by_sheet.items(), start=1):
            sheets.append(f'<sheet name="{name}" sheetId="{n}" r:id="rId{n}"/>')
            rels.append(f'<Relationship Id="rId{n}" Target="worksheets/sheet{n}.xml" '
                        'Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/worksheet"/>')
            body = "".join(
                f'<row r="{r + 1}">' + "".join(_cell(f"{_col(c)}{r + 1}", v) for c, v in enumerate(row)) + "</row>"
                for r, row in enumerate(rows)
            )
            z.writestr(f"xl/worksheets/sheet{n}.xml", f"<worksheet {ns}><sheetData>{body}</sheetData></worksheet>")
        z.writestr("xl/workbook.xml", f"<workbook {ns} {rel_ns}><sheets>{''.join(sheets)}</sheets></workbook>")
        z.writestr("xl/_rels/workbook.xml.rels",
                   '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">'
                   + "".join(rels) + "</Relationships>")


@pytest.fixture(scope="session")
def enemy_workbook(tmp_path_factory):
    """A small synthetic enemy workbook in the community sheet's layout."""
    path = tmp_path_factory.mktemp("wb") / "enemies.xlsx"
    sheets = {}
    for cycle, name in enumerate(CYCLE_SHEETS):
        scale = 1 + cycle
        sheets[name] = [
            [g.format(cycle=name) if g else g for g in GROUPS],
            HEADERS,
            _row("Castle", "Knight [Boss]", 5000.0 * scale, 100.0 + cycle, 400.0, 0.7),
            _row("Field", "Soldier", 800.0 * scale, 90.0, 200.0, 1.0),
            _row("Cave", "Soldier", 900.0 * scale, 95.0, 200.0, 1.0),
            _row("Lake", "Crab", "-", 90.0, 200.0, 1.0),  # no HP: skipped
            _row("Arena", "Chariot", 0.0, 90.0, 200.0, 1.0),  # 0 HP (can't be damaged): skipped
            _row("Tower", "Mage", 700.0 * scale, 100.0, 300.0, 1.0),  # two placements, same
            _row("Tower", "Mage", 700.0 * scale, 120.0, 300.0, 1.0),  # location, different stats
            _row("Tower", "Mage", 700.0 * scale, 100.0, 300.0, 1.0),  # duplicate of the first
        ]
    sheets["Item Drops"] = [["ignored"]]
    write_workbook(path, sheets)
    return path


@pytest.fixture
def xlsx_writer():
    """write_workbook(path, {sheet_name: rows}) for tests that need a custom workbook."""
    return write_workbook


@pytest.fixture(scope="session")
def enemy_cache(enemy_workbook, tmp_path_factory):
    """Path to an enemy JSON cache built from the synthetic workbook."""
    import json

    from erbuild.enemies import convert_workbook

    path = tmp_path_factory.mktemp("cache") / "enemies.json"
    path.write_text(json.dumps(convert_workbook(enemy_workbook)))
    return path
