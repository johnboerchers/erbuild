# erbuild

**Find the stat allocation that maximizes your weapon's damage in Elden Ring.**

You pick a starting class, a target level, a weapon, and how much Vigor (and Mind,
Endurance…) you want. erbuild works out exactly how to spend the rest of your points.

> **Status:** v0.2 adds the optimizer: exact AR-maximizing allocations, plus the
> trade-off between AR and arcane status buildup (bleed, poison…). It's built on an
> exact AR calculator validated against a reference implementation. See the
> [roadmap](#roadmap).

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

ar = attack_rating(katana, {"str": 12, "dex": 40, "arc": 50}, upgrade=25)
print(ar.displayed)        # per-type AR as shown in game
print(ar.displayed_total)

# Vectorized: evaluate thousands of stat allocations in one call
dex = np.arange(15, 100)
values = attack_power(katana, {"str": 12, "dex": dex, "arc": 50}, upgrade=25)
```

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
- [ ] Damage against a specific enemy (defense and absorption), and bleed procs per hit
- [ ] Buffs and talismans as multipliers
- [ ] Spell scaling for staves and seals
- [ ] Web UI

## Credits and license

MIT. Regulation data and the core formula are derived from
[elden-ring-weapon-calculator](https://github.com/ThomasJClark/elden-ring-weapon-calculator)
by Tom Clark (MIT). See [THIRD_PARTY_NOTICES.md](THIRD_PARTY_NOTICES.md).

Elden Ring is a trademark of FromSoftware / Bandai Namco. This is an unofficial fan
project.
