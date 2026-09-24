# erbuild

**Find the stat allocation that maximizes your weapon's damage in Elden Ring.**

You pick a starting class, a target level, a weapon, and how much Vigor (and Mind,
Endurance…) you want. erbuild works out exactly how to spend the rest of your points.

> **Status:** v0.1 is the foundation: an exact attack rating (AR) calculator built on
> datamined game parameters, validated against a reference implementation. The
> optimizer is next. See the [roadmap](#roadmap).

## Install

```bash
git clone https://github.com/johnboerchers/erbuild.git
cd erbuild
pip install -e .
```

Requires Python 3.10+ and NumPy.

## Quick start

### Command line

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
from erbuild import load_default, attack_rating, attack_power

reg = load_default()
katana = reg.get("Blood Uchigatana")

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

## Validation

`tests/fixtures/reference_ar.json` holds 3,000 randomized cases (random weapon, stats,
upgrade level and grip, biased toward requirement thresholds and soft caps) computed by
[Tom Clark's calculator](https://github.com/ThomasJClark/elden-ring-weapon-calculator),
a widely used tool known to match in-game values. erbuild matches every case to
floating-point precision:

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
- [ ] **Optimizer:** maximize AR given class, level, and fixed VIG/MND/END. This is exact
      dynamic programming, since AR is separable across attributes.
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
