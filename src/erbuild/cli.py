"""Command-line interface.

Examples:
    erbuild search uchigatana
    erbuild ar "Blood Uchigatana" --str 12 --dex 40 --arc 50
    erbuild ar "Rivers of Blood" --str 14 --dex 30 --arc 60 --upgrade 8 --two-handing
    erbuild optimize "Blood Uchigatana" --class samurai --level 150 --vig 60
    erbuild classes
"""

from __future__ import annotations

import argparse
import sys

import numpy as np

from .calculator import attack_rating
from .classes import STARTING_CLASSES
from .constants import ALL_ATTRIBUTES, LEVEL_OFFSET, SCALING_ATTRIBUTES
from .optimizer import optimize
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


def _parse_minimums(pairs: list[str]) -> dict[str, int]:
    out = {}
    for pair in pairs:
        attr, sep, value = pair.partition("=")
        if not sep or not value.strip().isdigit():
            raise ValueError(f"--min expects STAT=N (e.g. mnd=20), got {pair!r}")
        out[attr.strip().lower()] = int(value)
    return out


def _format_stats(attrs: dict[str, int], names: tuple[str, ...]) -> str:
    return "  ".join(f"{a.upper()} {attrs[a]}" for a in names)


def cmd_optimize(args: argparse.Namespace) -> int:
    reg = _load(args)
    try:
        weapon = reg.get(args.weapon)
        fixed = {a: getattr(args, a) for a in ALL_ATTRIBUTES if getattr(args, a) is not None}
        result = optimize(
            weapon,
            args.starting_class,
            args.level,
            upgrade=args.upgrade,
            two_handing=args.two_handing,
            fixed=fixed,
            minimum=_parse_minimums(args.min),
        )
    except (KeyError, ValueError) as e:
        print(e.args[0], file=sys.stderr)
        return 1

    status = result.status_types
    if args.min_buildup is not None:
        if not status:
            print(f"{weapon.key} has no status buildup that scales with arcane.", file=sys.stderr)
            return 1
        build = result.with_status_at_least(args.min_buildup, status[0])
        if build is None:
            top = max(b.status[status[0]] for b in result.frontier)
            print(f"No build reaches {status[0].label} {args.min_buildup:g} (max {top:.0f}).",
                  file=sys.stderr)
            return 1
        title = f"Highest AR with {status[0].label} >= {args.min_buildup:g}"
    else:
        build = result.best
        title = "Highest AR"

    grip = "two-handed" if args.two_handing else "one-handed"
    print(f"{weapon.key} +{result.upgrade} ({grip}) [{reg.version}]")
    constraints = [f"{result.starting_class.name}, level {result.level}"]
    if fixed:
        constraints.append("fixed " + _format_stats(fixed, tuple(fixed)))
    if args.min:
        minimum = _parse_minimums(args.min)
        constraints.append("min " + _format_stats(minimum, tuple(minimum)))
    print("  " + " | ".join(constraints))
    print()
    print(f"{title}: {build.rating.displayed_total}")
    print(f"  {_format_stats(build.attributes, ALL_ATTRIBUTES)}  ({build.free_points} free points)")
    if build.rating.ineffective_attributes:
        unmet = ", ".join(a.upper() for a in build.rating.ineffective_attributes)
        print(f"  ! Requirements deliberately left unmet: {unmet}")

    if len(result.frontier) > 1:
        rows = list(result.frontier)
        shown = rows if args.all else [rows[i] for i in sorted(
            {round(x) for x in np.linspace(0, len(rows) - 1, min(len(rows), 12))}
        )]
        labels = " / ".join(t.label.lower() for t in status)
        print()
        more = "" if len(shown) == len(rows) else f", showing {len(shown)} (--all for every one)"
        print(f"AR vs. {labels}: {len(rows)} Pareto-optimal builds{more}")
        header = f"{'AR':>6}" + "".join(f"{t.label:>9}" for t in status)
        header += "".join(f"{a.upper():>5}" for a in SCALING_ATTRIBUTES) + f"{'Free':>6}"
        print(header)
        for b in shown:
            shown_values = b.rating.displayed
            line = f"{b.rating.displayed_total:>6}"
            line += "".join(f"{shown_values.get(t, 0):>9}" for t in status)
            line += "".join(f"{b.attributes[a]:>5}" for a in SCALING_ATTRIBUTES)
            print(line + f"{b.free_points:>6}")
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

    o = sub.add_parser(
        "optimize",
        help="Find the stat allocation that maximizes AR",
        description="Find the stat allocation that maximizes AR. For weapons whose status "
        "buildup scales with arcane, shows the trade-off between AR and buildup.",
    )
    o.add_argument("weapon", help='Full weapon name including affinity, e.g. "Blood Uchigatana"')
    o.add_argument("--class", dest="starting_class", required=True, metavar="CLASS",
                   help="Starting class, e.g. samurai (see: erbuild classes)")
    o.add_argument("--level", "-l", type=int, required=True, metavar="N",
                   help="Target character level")
    for attr in ALL_ATTRIBUTES:
        o.add_argument(f"--{attr}", type=int, metavar="N", help=f"Fix {attr.upper()} at N")
    o.add_argument("--min", action="append", default=[], metavar="STAT=N",
                   help="Require STAT >= N (repeatable), e.g. --min mnd=20")
    o.add_argument("--upgrade", "-u", type=int, metavar="N", help="Upgrade level (default: max)")
    o.add_argument("--two-handing", "-2", action="store_true")
    o.add_argument("--min-buildup", type=float, metavar="N",
                   help="Best build whose arcane status buildup (e.g. bleed) is at least N")
    o.add_argument("--all", action="store_true", help="Print every Pareto-optimal build")
    o.set_defaults(func=cmd_optimize)

    c = sub.add_parser("classes", help="List starting classes and base stats")
    c.set_defaults(func=cmd_classes)
    return p


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    raise SystemExit(main())
