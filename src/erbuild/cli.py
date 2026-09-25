"""Command-line interface.

Examples:
    erbuild search uchigatana
    erbuild ar "Blood Uchigatana" --str 12 --dex 40 --arc 50
    erbuild ar "Rivers of Blood" --str 14 --dex 30 --arc 60 --upgrade 8 --two-handing
    erbuild optimize "Blood Uchigatana" --class samurai --level 150 --vig 60
    erbuild enemies update
    erbuild optimize "Blood Uchigatana" --class samurai --level 150 --vig 60 \\
        --enemy "Malenia, Blade of Miquella [Boss]"
    erbuild classes
"""

from __future__ import annotations

import argparse
import math
import sys
import zipfile

import numpy as np

from .calculator import attack_rating
from .classes import STARTING_CLASSES
from .constants import ALL_ATTRIBUTES, LEVEL_OFFSET, SCALING_ATTRIBUTES
from .damage import HitDamage, bleed_flat_damage, hit_breakdown
from .enemies import (
    ATTACK_TYPES,
    CYCLE_SHEETS,
    DAMAGE_TYPE_KEYS,
    SHEET_URL,
    Enemy,
    load_enemies,
    parse_cycle,
    update_enemy_data,
)
from .optimizer import Build, optimize, optimize_vs_enemy
from .regulation import Regulation

_BLEED_NOTE = ("Bleed is averaged over its proc cycle, using the first proc's length; "
               "see the README for how it's modeled.")


def _number_type(minimum: float, inclusive: bool, integer: bool = False):
    """argparse type: a finite number above (or at) `minimum`, with a readable error."""
    def parse(text: str):
        try:
            value = int(text) if integer else float(text)
        except ValueError:
            kind = "a whole number" if integer else "a number"
            raise argparse.ArgumentTypeError(f"expected {kind}, got {text!r}") from None
        if not math.isfinite(value):
            raise argparse.ArgumentTypeError(f"must be a finite number, got {text}")
        ok = value >= minimum if inclusive else value > minimum
        if not ok:
            bound = f"at least {minimum:g}" if inclusive else f"greater than {minimum:g}"
            raise argparse.ArgumentTypeError(f"must be {bound}, got {text}")
        return value
    return parse


_positive = _number_type(0, inclusive=False)
_non_negative = _number_type(0, inclusive=True)
_positive_int = _number_type(1, inclusive=True, integer=True)
_non_negative_int = _number_type(0, inclusive=True, integer=True)


def _load(args: argparse.Namespace) -> Regulation:
    return Regulation.load(args.data)


def _error(message: str) -> int:
    print(message, file=sys.stderr)
    return 1


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


# ---------------------------------------------------------------------- enemy helpers
def _add_enemy_args(parser: argparse.ArgumentParser, help_suffix: str) -> None:
    g = parser.add_argument_group("enemy", f"Damage against an enemy {help_suffix}")
    g.add_argument("--enemy", metavar="NAME",
                   help='Enemy name as in `erbuild enemies search`, e.g. "Malenia, Blade of Miquella [Boss]"')
    g.add_argument("--location", metavar="TEXT",
                   help="Pick a placement when the enemy appears in several places")
    g.add_argument("--variant", type=_positive_int, metavar="N",
                   help="Pick one of several placements in the same location (listed when needed)")
    g.add_argument("--cycle", default="ng", metavar="NG",
                   help="Journey cycle: ng, ng+, ng+2 … ng+7 (default: ng)")
    g.add_argument("--mv", type=_positive, default=100.0, metavar="N",
                   help="Motion value of the attack (default: 100)")
    g.add_argument("--attack-type", choices=ATTACK_TYPES, default="standard",
                   help="Physical attack type (default: standard)")
    g.add_argument("--bleed-flat", type=_non_negative, metavar="N",
                   help="Flat part of a bleed proc (default: 100 or 200 depending on weapon)")


def _load_enemy(args: argparse.Namespace) -> Enemy:
    data = load_enemies(args.enemy_data)
    return data.get(args.enemy, parse_cycle(args.cycle), args.location, args.variant)


def _enemy_line(enemy: Enemy, args: argparse.Namespace) -> str:
    where = f"{enemy.location}, " if enemy.location else ""
    return (f"vs {enemy.name} ({where}{enemy.cycle_name}) | "
            f"MV {args.mv:g}, {args.attack_type} attack")


def _bleed_detail(damage: HitDamage) -> str:
    return f"{damage.bleed_proc:.0f} per proc, every {damage.hits_to_proc:.0f} hits"


def _hit_summary(damage: HitDamage) -> str:
    if not damage.bleed_proc:
        return f"direct {damage.direct:.0f}"
    return (f"direct {damage.direct:.0f} + bleed {damage.bleed_per_hit:.0f} "
            f"({_bleed_detail(damage)})")


# ---------------------------------------------------------------------- ar
def cmd_ar(args: argparse.Namespace) -> int:
    reg = _load(args)
    try:
        weapon = reg.get(args.weapon)
        enemy = _load_enemy(args) if args.enemy else None
    except (KeyError, ValueError, FileNotFoundError) as e:
        return _error(e.args[0])
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

    if enemy is not None:
        flat = args.bleed_flat if args.bleed_flat is not None else bleed_flat_damage(weapon, reg)
        damage = hit_breakdown(ar.values, enemy, args.mv, args.attack_type, flat)
        print()
        print(_enemy_line(enemy, args))
        print(f"  {'Direct':<14} {damage.direct:>5.0f}")
        if damage.bleed_proc:
            print(f"  {'Bleed':<14} {damage.bleed_per_hit:>5.0f}  ({_bleed_detail(damage)})")
        print(f"  {'Per hit':<14} {damage.total:>5.0f}")
        if damage.bleed_proc:
            print(f"  {_BLEED_NOTE}")
    return 0


# ---------------------------------------------------------------------- optimize
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


def _print_build(build: Build) -> None:
    print(f"  {_format_stats(build.attributes, ALL_ATTRIBUTES)}  ({build.free_points} free points)")
    if build.rating.ineffective_attributes:
        unmet = ", ".join(a.upper() for a in build.rating.ineffective_attributes)
        print(f"  ! Requirements deliberately left unmet: {unmet}")


def cmd_optimize(args: argparse.Namespace) -> int:
    reg = _load(args)
    try:
        weapon = reg.get(args.weapon)
        fixed = {a: getattr(args, a) for a in ALL_ATTRIBUTES if getattr(args, a) is not None}
        minimum = _parse_minimums(args.min)
        options = dict(upgrade=args.upgrade, two_handing=args.two_handing,
                       fixed=fixed, minimum=minimum)
        if args.enemy:
            if args.min_buildup is not None:
                raise ValueError("--min-buildup can't be combined with --enemy: against an "
                                 "enemy, bleed is already weighed into damage per hit")
            enemy = _load_enemy(args)
            result = optimize_vs_enemy(
                weapon, args.starting_class, args.level, enemy, **options,
                motion_value=args.mv, attack_type=args.attack_type,
                bleed_flat=args.bleed_flat, regulation=reg,
            )
        else:
            result = optimize(weapon, args.starting_class, args.level, **options)
    except (KeyError, ValueError, FileNotFoundError) as e:
        return _error(e.args[0])

    grip = "two-handed" if args.two_handing else "one-handed"
    header = [f"{weapon.key} +{result.upgrade} ({grip}) [{reg.version}]"]
    constraints = [f"{result.starting_class.name}, level {result.level}"]
    if fixed:
        constraints.append("fixed " + _format_stats(fixed, tuple(fixed)))
    if minimum:
        constraints.append("min " + _format_stats(minimum, tuple(minimum)))
    header.append("  " + " | ".join(constraints))

    if args.enemy:
        return _print_enemy_result(result, header, args)
    return _print_frontier_result(result, header, args)


def _print_enemy_result(result, header: list[str], args: argparse.Namespace) -> int:
    header.append("  " + _enemy_line(result.enemy, args))
    print("\n".join(header))
    print()
    best, ar_best = result.best, result.highest_ar
    print(f"Most damage per hit: {best.damage.total:.0f}")
    _print_build(best.build)
    print(f"  AR {best.build.rating.displayed_total} | {_hit_summary(best.damage)}")
    print()
    gain = best.damage.total / ar_best.damage.total - 1 if ar_best.damage.total else 0.0
    if best.build.attributes == ar_best.build.attributes:
        print("This is also the highest-AR build.")
    else:
        verdict = (f"the build above does {gain:.1%} more" if gain >= 0.0005
                   else "practically the same as the build above")
        print(f"For comparison, the highest-AR build: {ar_best.damage.total:.0f} per hit ({verdict})")
        _print_build(ar_best.build)
        print(f"  AR {ar_best.build.rating.displayed_total} | {_hit_summary(ar_best.damage)}")
    if best.damage.bleed_proc or ar_best.damage.bleed_proc:
        print()
        print(_BLEED_NOTE)
    return 0


def _print_frontier_result(result, header: list[str], args: argparse.Namespace) -> int:
    status = result.status_types
    if args.min_buildup is not None:
        if not status:
            return _error(f"{result.weapon.key} has no status buildup that scales with arcane.")
        build = result.with_status_at_least(args.min_buildup, status[0])
        if build is None:
            top = max(b.status[status[0]] for b in result.frontier)
            return _error(f"No build reaches {status[0].label} {args.min_buildup:g} (max {top:.0f}).")
        title = f"Highest AR with {status[0].label} >= {args.min_buildup:g}"
    else:
        build = result.best
        title = "Highest AR"

    print("\n".join(header))
    print()
    print(f"{title}: {build.rating.displayed_total}")
    _print_build(build)

    if len(result.frontier) > 1:
        rows = list(result.frontier)
        shown = rows if args.all else [rows[i] for i in sorted(
            {round(x) for x in np.linspace(0, len(rows) - 1, min(len(rows), 12))}
        )]
        labels = " / ".join(t.label.lower() for t in status)
        print()
        more = "" if len(shown) == len(rows) else f", showing {len(shown)} (--all for every one)"
        print(f"AR vs. {labels}: {len(rows)} Pareto-optimal builds{more}")
        line = f"{'AR':>6}" + "".join(f"{t.label:>9}" for t in status)
        line += "".join(f"{a.upper():>5}" for a in SCALING_ATTRIBUTES) + f"{'Free':>6}"
        print(line)
        for b in shown:
            shown_values = b.rating.displayed
            line = f"{b.rating.displayed_total:>6}"
            line += "".join(f"{shown_values.get(t, 0):>9}" for t in status)
            line += "".join(f"{b.attributes[a]:>5}" for a in SCALING_ATTRIBUTES)
            print(line + f"{b.free_points:>6}")
    return 0


# ---------------------------------------------------------------------- enemies
def cmd_enemies_update(args: argparse.Namespace) -> int:
    print(f"Downloading enemy data from {SHEET_URL} …")
    try:
        path = update_enemy_data(args.enemy_data)
    except OSError as e:
        return _error(f"Download failed: {e}")
    except (zipfile.BadZipFile, ValueError, KeyError) as e:
        return _error(f"The download wasn't the expected enemy workbook ({e}). "
                      "The sheet may have moved or changed format.")
    data = load_enemies(path)
    print(f"Saved {len(data)} enemy placements × {len(CYCLE_SHEETS)} cycles to {path}")
    print("Enemy data: 'Elden Ring PvE Enemy Health / Defense Data' community sheet.")
    return 0


def cmd_enemies_search(args: argparse.Namespace) -> int:
    try:
        data = load_enemies(args.enemy_data)
        hits = data.search(args.query, parse_cycle(args.cycle), limit=args.limit)
    except (ValueError, FileNotFoundError) as e:
        return _error(e.args[0])
    if not hits:
        return _error(f"No enemies matching {args.query!r}")
    for e in hits:
        print(f"{e.name:<50} {e.hp:>8,.0f} HP   {e.location}")
    return 0


def cmd_enemies_show(args: argparse.Namespace) -> int:
    try:
        enemy = _load_enemy(args)
    except (KeyError, ValueError, FileNotFoundError) as e:
        return _error(e.args[0])
    print(f"{enemy.name} ({enemy.location}, {enemy.cycle_name})")
    print(f"  HP {enemy.hp:,.0f}")
    print()
    keys = ["standard", "strike", "slash", "pierce", *DAMAGE_TYPE_KEYS.values()]
    print(f"  {'':<12}" + "".join(f"{k.title():>10}" for k in keys))
    print(f"  {'Defense':<12}" + "".join(f"{enemy.defense[k]:>10g}" for k in keys))
    print(f"  {'Negation %':<12}" + "".join(f"{enemy.negation[k]:>10g}" for k in keys))
    print()
    for t, r in enemy.resistance.items():
        mult = enemy.status_multiplier.get(t)
        extra = f"   (takes ×{mult:g} damage)" if mult not in (None, 1.0) else ""
        print(f"  {t.label:<12} {'immune' if r is None else f'{r:g}':>8}{extra}")
    return 0


# ---------------------------------------------------------------------- classes
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
    p.add_argument("--enemy-data", metavar="PATH",
                   help="Enemy data cache (default: ~/.cache/erbuild/enemies.json)")
    sub = p.add_subparsers(dest="command", required=True)

    s = sub.add_parser("search", help="Find weapons by name")
    s.add_argument("query")
    s.add_argument("--limit", type=_positive_int, default=20)
    s.set_defaults(func=cmd_search)

    a = sub.add_parser("ar", help="Compute attack rating for a weapon and attributes")
    a.add_argument("weapon", help='Full weapon name including affinity, e.g. "Blood Uchigatana"')
    for attr in SCALING_ATTRIBUTES:
        a.add_argument(f"--{attr}", type=int, default=10, metavar="N")
    a.add_argument("--upgrade", "-u", type=_non_negative_int, metavar="N",
                   help="Upgrade level (default: max)")
    a.add_argument("--two-handing", action="store_true")
    _add_enemy_args(a, "(prints damage per hit)")
    a.set_defaults(func=cmd_ar)

    o = sub.add_parser(
        "optimize",
        help="Find the stat allocation that maximizes AR or damage",
        description="Find the stat allocation that maximizes AR. For weapons whose status "
        "buildup scales with arcane, shows the trade-off between AR and buildup. With "
        "--enemy, maximizes damage per hit against that enemy instead, bleed included.",
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
    o.add_argument("--upgrade", "-u", type=_non_negative_int, metavar="N",
                   help="Upgrade level (default: max)")
    o.add_argument("--two-handing", action="store_true")
    o.add_argument("--min-buildup", type=_non_negative, metavar="N",
                   help="Best build whose arcane status buildup (e.g. bleed) is at least N")
    o.add_argument("--all", action="store_true", help="Print every Pareto-optimal build")
    _add_enemy_args(o, "(optimizes damage per hit instead of AR)")
    o.set_defaults(func=cmd_optimize)

    e = sub.add_parser("enemies", help="Download, search and inspect enemy data")
    esub = e.add_subparsers(dest="enemies_command", required=True)
    eu = esub.add_parser("update", help="Download the enemy data sheet to the local cache")
    eu.set_defaults(func=cmd_enemies_update)
    es = esub.add_parser("search", help="Find enemies by name")
    es.add_argument("query")
    es.add_argument("--cycle", default="ng", metavar="NG", help="Journey cycle (default: ng)")
    es.add_argument("--limit", type=_positive_int, default=20)
    es.set_defaults(func=cmd_enemies_search)
    eshow = esub.add_parser("show", help="Show an enemy's HP, defenses and resistances")
    eshow.add_argument("enemy", metavar="NAME")
    eshow.add_argument("--location", metavar="TEXT", help="Pick a placement by location")
    eshow.add_argument("--variant", type=_positive_int, metavar="N",
                       help="Pick one of several placements in the same location")
    eshow.add_argument("--cycle", default="ng", metavar="NG", help="Journey cycle (default: ng)")
    eshow.set_defaults(func=cmd_enemies_show)

    c = sub.add_parser("classes", help="List starting classes and base stats")
    c.set_defaults(func=cmd_classes)
    return p


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        return args.func(args)
    except (KeyError, ValueError, FileNotFoundError) as e:
        return _error(str(e.args[0]) if e.args else type(e).__name__)


if __name__ == "__main__":
    raise SystemExit(main())
