# erbuild

**Find the stat allocation that maximizes your weapon's damage in Elden Ring.**

You pick a starting class, a target level, a weapon, and how much Vigor (and Mind,
Endurance…) you want. erbuild works out exactly how to spend the rest of your points.

> **Status:** v0.3 optimizes against specific enemies: damage per hit through the
> enemy's defenses, with bleed procs included. v0.2 added the exact AR optimizer and
> the AR vs. arcane buildup trade-off, on top of an AR calculator validated against a
> reference implementation. See the [roadmap](#roadmap).

## Install

```bash
git clone https://github.com/johnboerchers/erbuild.git
cd erbuild
pip install -e .
```

Requires Python 3.10+ and NumPy.

## Quick start

### Command line

Find the best allocation for a build:

```console
$ erbuild optimize "Blood Uchigatana" --class samurai --level 150 --vig 60
Blood Uchigatana +25 (one-handed) [vanilla-v1.17]
  Samurai, level 150 | fixed VIG 60

Highest AR: 522
  VIG 60  MND 11  END 13  STR 51  DEX 59  INT 9  FAI 8  ARC 18  (0 free points)

AR vs. bleed: 82 Pareto-optimal builds, showing 12 (--all for every one)
    AR    Bleed  STR  DEX  INT  FAI  ARC  Free
   522       84   51   59    9    8   18     0
   521       85   45   58    9    8   25     0
   518       94   38   57    9    8   33     0
   514      102   31   57    9    8   40     0
   509      109   25   56    9    8   47     0
   502      112   18   55    9    8   55     0
   ...
   407      117   12   17    9    8   99     0
```

Each row is the best AR you can have at that much bleed buildup, so you can see what
each extra point of bleed costs. Useful options:

- `--vig 60`, `--mnd 20`, … fix any attribute at an exact value.
- `--min mnd=20` requires an attribute to be *at least* a value (repeatable).
- `--min-buildup 110` picks the highest-AR build with at least that much buildup.
- `--two-handing` / `-2` and `--upgrade N` set the grip and upgrade level.

Points that wouldn't raise AR are left unassigned and shown as *free points*: put them
wherever you like.

Or compute AR for a specific set of stats:

```console
$ erbuild search uchigatana
Uchigatana                               Katana               +25  req: STR 11 DEX 15
Cold Uchigatana                          Katana               +25  req: STR 11 DEX 15
...

$ erbuild ar "Blood Uchigatana" --str 12 --dex 40 --arc 50
Blood Uchigatana +25 (one-handed) [vanilla-v1.17]
  Attributes: STR 12  DEX 40  INT 10  FAI 10  ARC 50
  Scaling:    STR C  DEX B  ARC D

  Physical       445
  Total          445

  Bleed          110  (buildup)

$ erbuild ar "Rivers of Blood" --str 14 --dex 30 --arc 60 --upgrade 10 --two-handing
$ erbuild classes
```

Weapon names include the affinity (`"Heavy Claymore"`, `"Blood Uchigatana"`). If you
misspell one, erbuild suggests close matches.

### Against a specific enemy

AR is what the equipment screen shows. Against a real enemy, defenses, damage
negation and bleed resistance change which build is best. Download the enemy data
once, then add `--enemy`:

```console
$ erbuild enemies update
$ erbuild enemies search malenia
Malenia, Goddess of Rot [Boss]                       18,473 HP   Miquella's Haligtree - Elphael
Malenia, Blade of Miquella [Boss]                    18,473 HP   Miquella's Haligtree - Elphael

$ erbuild optimize "Blood Uchigatana" --class samurai --level 150 --vig 60 \
    --enemy "Malenia, Blade of Miquella [Boss]"
Blood Uchigatana +25 (one-handed) [vanilla-v1.17]
  Samurai, level 150 | fixed VIG 60
  vs Malenia, Blade of Miquella [Boss] (Miquella's Haligtree - Elphael, NG) | MV 100, standard attack

Most damage per hit: 891
  VIG 60  MND 11  END 13  STR 30  DEX 56  INT 9  FAI 8  ARC 42  (0 free points)
  AR 513 | direct 371 + bleed 520 (2080 per proc, every 4 hits)

For comparison, the highest-AR build: 796 per hit (the build above does 12.0% more)
  VIG 60  MND 11  END 13  STR 51  DEX 59  INT 9  FAI 8  ARC 18  (0 free points)
  AR 522 | direct 380 + bleed 416 (2080 per proc, every 5 hits)
```

Enemy options (they also work with `erbuild ar` to score one build):

- `--cycle ng+2` picks the journey (NG through NG+7).
- `--location "castle"` picks a placement when an enemy appears in several places.
- `--attack-type slash` sets the physical attack type (`standard`, `strike`, `slash`
  or `pierce`); enemies have a separate defense and negation for each.
- `--mv 130` sets the attack's motion value (default 100, the weapon's full AR).
- `--bleed-flat 200` overrides the flat part of a bleed proc.

`erbuild enemies show "Mohg, Lord of Blood [Boss]"` prints an enemy's HP, defenses,
negations and resistances.

### Python

```python
import numpy as np
from erbuild import load_default, attack_rating, attack_power, optimize

reg = load_default()
katana = reg.get("Blood Uchigatana")

result = optimize(katana, "samurai", 150, fixed={"vig": 60}, minimum={"mnd": 20})
print(result.best.attributes, result.best.ar)
for build in result.frontier:          # Pareto frontier of AR vs. bleed
    print(build.ar, build.status, build.free_points)
build = result.with_status_at_least(110)

from erbuild import load_enemies, optimize_vs_enemy   # after `erbuild enemies update`

malenia = load_enemies().get("Malenia, Blade of Miquella [Boss]", cycle=0)
vs = optimize_vs_enemy(katana, "samurai", 150, malenia, fixed={"vig": 60}, attack_type="slash")
print(vs.best.build.attributes, vs.best.damage.total, vs.best.damage.hits_to_proc)

ar = attack_rating(katana, {"str": 12, "dex": 40, "arc": 50}, upgrade=25)
print(ar.displayed)        # per-type AR as shown in game
print(ar.displayed_total)

# Vectorized: evaluate thousands of stat allocations in one call
dex = np.arange(15, 100)
values = attack_power(katana, {"str": 12, "dex": dex, "arc": 50}, upgrade=25)
```

### In the browser

[`web/`](web/) holds a static web app that runs erbuild in the browser via Pyodide:
the same Python code, with no server. It has the optimizer (with an interactive AR
vs. bleed chart), the AR calculator, and damage against enemies. See
[web/README.md](web/README.md) to run it locally.

## How AR is calculated

For every attack power type *t* (physical, magic, fire, lightning, holy, plus status
buildup like bleed), a weapon at upgrade level *u* has:

$$
\mathrm{AR}_t = B_t(u)\left(1 + \sum_{s} m_{t,s}\, S_s(u)\, g_t(a_s)\right)
$$

| Symbol | Meaning | Game param |
|---|---|---|
| $B_t(u)$ | base attack at upgrade *u* | `EquipParamWeapon` × `ReinforceParamWeapon` |
| $S_s(u)$ | scaling coefficient for attribute *s* (the letter grade is a bin of this) | same |
| $m_{t,s}$ | 1 if type *t* scales with attribute *s* | `AttackElementCorrectParam` |
| $g_t(x)$ | piecewise "soft cap" curve, 0 at 1 and ~1 at the hard cap | `CalcCorrectGraph` |
| $a_s$ | your attribute value (STR is ⌊1.5·STR⌋ when two-handing) | – |

A few details matter for exact results:

- **Unmet requirements:** if any attribute that type *t* scales with is below the
  requirement, that type's AR becomes $0.6\,B_t(u)$ with no scaling.
- **Two-handing:** raises effective STR for both the requirement check and damage
  scaling, but *not* for status buildup. Paired weapons never get the bonus, and bows
  always do.
- **Display:** the game truncates each type to an integer. The total is the truncated
  sum of the unrounded values.

## How the optimizer works

Given a starting class (whose stats are the minimums), a target level *L*, and any
fixed or minimum attributes, the points to spend are

$$
N = L + 79 - \sum_i \ell_i
$$

where $\ell_i$ is each attribute's lower bound (every class satisfies
level = Σ attributes − 79). The optimizer maximizes the unrounded total AR. It uses
three facts about the formula above:

1. **Buildup depends only on arcane.** Bleed, poison, madness and sleep scale with raw
   arcane alone, so each arcane value gives exactly one buildup value. The AR vs.
   buildup frontier is a sweep: for every arcane value, find the best AR, then drop
   builds that another build beats on both.
2. **AR is separable.** Once you fix which requirements are met, AR is a constant plus
   one lookup table per attribute. Maximizing that under a point budget is a
   nonlinear integer knapsack, which dynamic programming solves *exactly*. A single DP
   over STR/DEX/INT/FAI gives the best AR for every arcane value at once:
   $\mathrm{AR}(a) = C + h_{\mathrm{arc}}(a) + V(N - a)$.
3. **Requirements are the only coupling.** The optimizer tries each combination of
   requirements met/unmet (at most 32) and keeps the best, so it will leave a
   requirement unmet when that's genuinely better.

Why not simply add each point where it helps most? Soft-cap curves start out
convex and requirements create cliffs, so that greedy approach can get stuck on a
worse build. The whole optimization takes a few milliseconds.

## How damage against an enemy works

For each damage type, the game compares your attack to the enemy's defense with the
attack ratio $r = \mathrm{AR}_t \cdot \mathrm{MV} / \mathrm{Def}_t$ and applies a
piecewise curve $m(r)$, from 10% at low ratios up to 90% at $r \ge 8$
([details](https://eldenring.wiki.fextralife.com/Calculating+Damage)):

| r | m(r) |
|---|---|
| < 0.125 | 0.10 |
| 0.125 – 1 | 0.10 + (r − 0.125)² / 2.552 |
| 1 – 2.5 | 0.70 − (2.5 − r)² / 7.5 |
| 2.5 – 8 | 0.90 − (8 − r)² / 151.25 |
| ≥ 8 | 0.90 |

Damage per hit adds each type's $\mathrm{AR}_t \cdot \mathrm{MV} \cdot m(r) \cdot
(1 - \text{negation}_t)$, plus bleed averaged over the hits it takes to proc:

$$
\text{bleed per hit} = \frac{\beta\,(0.15\,\mathrm{HP} + F)}{\lceil R / \text{buildup} \rceil}
$$

where $R$ is the enemy's bleed resistance and $\beta$ its incoming bleed multiplier
(0.7 for most base-game bosses, 0.5 for Mohg and most DLC bosses). The flat part $F$ is
200 for Reduvia, Morgott's Cursed Sword, Varre's Bouquet, Hoslow's Petal Whip and
Blood-infused weapons with innate bleed, and 100 otherwise
([source](https://eldenring.wiki.fextralife.com/Hemorrhage)).

**Solving it.** For a weapon with one damage type, like Blood Uchigatana, the best
build against *any* enemy lies on the AR vs. buildup frontier above. For a fixed arcane
value, bleed is fixed and damage rises with AR. So erbuild just scores those builds.
With split damage (e.g. physical + fire), each type passes through the defense curve
separately and that shortcut no longer holds. erbuild then enumerates every
allocation of the stats that matter. Damage never drops when you add a point, so only
allocations that spend the whole budget need checking.

### Simplifications

Bleed is modeled more simply than the game handles it. Keep these in mind:

- **Resistance rises after each proc.** The game raises an enemy's threshold after
  every proc, via `ResistanceCorrectParam` (for one common profile: ×1.3, ×1.77,
  ×2.44, ×4.0, then ×8.6). The enemy data doesn't say which profile each enemy uses,
  so erbuild counts hits to the **first** proc. Over a long fight this overstates
  bleed, and so can favor arcane more than it should.
- **Buildup decay** between hits is ignored.
- **Every hit applies the weapon's full buildup.** Some moves apply more or less.
- **Other statuses deal no damage here.** Poison, scarlet rot and frost aren't
  modeled yet; only bleed adds damage.
- **Motion value and attack type are inputs.** They depend on the move, and the
  default (MV 100, standard) is a reasonable baseline, not a specific attack.

### Enemy data

Enemy stats come from the community
[Elden Ring PvE Enemy Health / Defense Data](https://docs.google.com/spreadsheets/d/1BVwmKqB8pvuyJkSTGYOM2kAJxFMQ0jVsc6aKYz_Upes/edit)
sheet. It covers 3,254 enemy placements for every journey from NG to NG+7, derived
from the game's params with each placement's area scaling applied. The sheet has no
stated license, so erbuild **doesn't include it**. `erbuild enemies update` downloads
it on your machine and saves a converted copy to `~/.cache/erbuild/enemies.json` (or
`$ERBUILD_CACHE`, or `--enemy-data PATH`). All credit for the data goes to the sheet's
authors.

## Validation

`tests/fixtures/reference_ar.json` holds 3,000 randomized cases (random weapon, stats,
upgrade level and grip, biased toward requirement thresholds and soft caps) computed by
[Tom Clark's calculator](https://github.com/ThomasJClark/elden-ring-weapon-calculator),
a widely used tool known to match in-game values. erbuild matches every case to
floating-point precision:

The optimizer is checked against brute-force enumeration of every allocation on
200 random cases (weapons, classes, levels, grips, fixed and minimum attributes, with
small budgets so enumeration is feasible): it must find the same best AR for every
arcane value, spend the same minimum number of points, and return the same frontier.

The enemy mode is checked the same way on 120 random cases with randomized enemies
(defenses, negations, HP, bleed resistance, immunity), for both the frontier shortcut
and full enumeration. Tests never download the real enemy data: they use a small
synthetic workbook in the same format.

```bash
pytest
```

**In-game checks wanted!** `tests/fixtures/ingame_ar.csv` is for values read straight
off the equipment screen. If you add rows from your own save (and note the patch),
please open a PR.

## Updating game data

Game patches change weapon params. The bundled data is vanilla v1.17. To add a newer
version:

```bash
python scripts/fetch_regulation.py vanilla-v1.18
erbuild --data src/erbuild/data/regulation-vanilla-v1.18.json ar "Uchigatana" --dex 40
```

## Roadmap

- [x] Exact AR calculator (damage and status buildup), vectorized with NumPy
- [x] Starting classes and the level identity: level = Σ attributes − 79
- [x] **Optimizer:** maximize AR given class, level, and fixed or minimum attributes
      (exact dynamic programming), with the AR vs. arcane buildup Pareto frontier
- [x] Damage against a specific enemy (defense, negation, NG+ cycles) with bleed
      procs per hit
- [ ] Bleed after the first proc (per-enemy resistance growth), and poison/rot/frost damage
- [ ] Per-move motion values and physical attack types
- [ ] Optimizing against a set of enemies (weighted average or worst case)
- [ ] Buffs and talismans as multipliers
- [ ] Spell scaling for staves and seals
- [x] Web UI: optimizer, calculator and enemy damage, running in the browser (`web/`)
- [ ] Publish the web UI (GitHub Pages)

## Credits and license

MIT. Regulation data and the core formula are derived from
[elden-ring-weapon-calculator](https://github.com/ThomasJClark/elden-ring-weapon-calculator)
by Tom Clark (MIT). See [THIRD_PARTY_NOTICES.md](THIRD_PARTY_NOTICES.md).

Enemy data is not included: `erbuild enemies update` downloads the community
[Elden Ring PvE Enemy Health / Defense Data](https://docs.google.com/spreadsheets/d/1BVwmKqB8pvuyJkSTGYOM2kAJxFMQ0jVsc6aKYz_Upes/edit)
sheet on your machine (see [Enemy data](#enemy-data)).

Elden Ring is a trademark of FromSoftware / Bandai Namco. This is an unofficial fan
project.
