"""Command-line interface.

Examples:
    erbuild search uchigatana
    erbuild ar "Blood Uchigatana" --str 12 --dex 40 --arc 50
    erbuild ar "Rivers of Blood" --str 14 --dex 30 --arc 60 --upgrade 8 --two-handing
    erbuild classes
"""

from __future__ import annotations

import argparse
import sys

from .calculator import attack_rating
from .classes import STARTING_CLASSES
from .constants import ALL_ATTRIBUTES, LEVEL_OFFSET, SCALING_ATTRIBUTES
from .regulation import Regulation


def _load(args: argparse.Namespace) -> Regulation:
    return Regulation.load(args.data)


def cmd_search(args: argparse.Namespace) -> int:
    reg = _load(args)
    hits = reg.search(args.query, limit=args.limit)
    if not hits:
        print(f"No weapons matching {args.query!r}")
        return 1
    for w in hits:
        reqs = " ".join(f"{a.upper()} {v}" for a, v in w.requirements.items())
        print(f"{w.key:<40} {w.weapon_type_name:<20} +{w.max_upgrade:<3} req: {reqs}")
    return 0


def cmd_ar(args: argparse.Namespace) -> int:
    reg = _load(args)
    try:
        weapon = reg.get(args.weapon)
    except KeyError as e:
        print(e.args[0], file=sys.stderr)
        return 1
    attrs = {a: getattr(args, a) for a in SCALING_ATTRIBUTES}
    upgrade = weapon.max_upgrade if args.upgrade is None else args.upgrade
    ar = attack_rating(weapon, attrs, upgrade, two_handing=args.two_handing)

    grip = "two-handed" if args.two_handing else "one-handed"
    print(f"{weapon.key} +{upgrade} ({grip}) [{reg.version}]")
    stats = "  ".join(f"{a.upper()} {v}" for a, v in attrs.items())
    print(f"  Attributes: {stats}")
    grades = "  ".join(
        f"{a.upper()} {weapon.scaling_grade(a, upgrade, reg.scaling_tiers)}"
        for a in SCALING_ATTRIBUTES
        if weapon.attribute_scaling[upgrade].get(a)
    )
    print(f"  Scaling:    {grades or 'none'}")
    if ar.ineffective_attributes:
        print(f"  ! Requirements not met: {', '.join(a.upper() for a in ar.ineffective_attributes)}")
    print()
    for t, v in ar.displayed.items():
        if t.is_damage:
            print(f"  {t.label:<12} {v:>5}")
    print(f"  {'Total':<12} {ar.displayed_total:>5}")
    status = {t: v for t, v in ar.displayed.items() if t.is_status}
    if status:
        print()
        for t, v in status.items():
            print(f"  {t.label:<12} {v:>5}  (buildup)")
    return 0


def cmd_classes(args: argparse.Namespace) -> int:
    header = "  ".join(f"{a.upper():>3}" for a in ALL_ATTRIBUTES)
    print(f"{'Class':<12} {'Lvl':>3}  {header}")
    for c in STARTING_CLASSES.values():
        row = "  ".join(f"{c.stats[a]:>3}" for a in ALL_ATTRIBUTES)
        print(f"{c.name:<12} {c.level:>3}  {row}")
    print(f"\nLevel = sum of all attributes - {LEVEL_OFFSET}")
    return 0


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="erbuild", description=__doc__.splitlines()[0])
    p.add_argument("--data", help="Path to a regulation JSON file (default: bundled vanilla data)")
    sub = p.add_subparsers(dest="command", required=True)

    s = sub.add_parser("search", help="Find weapons by name")
    s.add_argument("query")
    s.add_argument("--limit", type=int, default=20)
    s.set_defaults(func=cmd_search)

    a = sub.add_parser("ar", help="Compute attack rating for a weapon and attributes")
    a.add_argument("weapon", help='Full weapon name including affinity, e.g. "Blood Uchigatana"')
    for attr in SCALING_ATTRIBUTES:
        a.add_argument(f"--{attr}", type=int, default=10, metavar="N")
    a.add_argument("--upgrade", "-u", type=int, help="Upgrade level (default: max)")
    a.add_argument("--two-handing", "-2", action="store_true")
    a.set_defaults(func=cmd_ar)

    c = sub.add_parser("classes", help="List starting classes and base stats")
    c.set_defaults(func=cmd_classes)
    return p


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    raise SystemExit(main())
