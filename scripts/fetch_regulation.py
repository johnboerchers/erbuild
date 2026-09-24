"""Download regulation data from the elden-ring-weapon-calculator repository.

When the game is patched, the upstream project publishes a new
public/regulation-vanilla-vX.YY.js file (plain JSON despite the extension).

Usage:
    python scripts/fetch_regulation.py vanilla-v1.17
    python scripts/fetch_regulation.py vanilla-v1.18 --out src/erbuild/data

After adding a new version, bump DEFAULT_VERSION in src/erbuild/regulation.py and
regenerate tests/fixtures/reference_ar.json (see scripts/generate_reference_fixtures.mjs).
"""

from __future__ import annotations

import argparse
import json
import urllib.request
from pathlib import Path

BASE = "https://raw.githubusercontent.com/ThomasJClark/elden-ring-weapon-calculator/main/public"


def main() -> None:
    p = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    p.add_argument("version", help="e.g. vanilla-v1.17")
    p.add_argument("--out", default="src/erbuild/data", help="Output directory")
    args = p.parse_args()

    url = f"{BASE}/regulation-{args.version}.js"
    print(f"Downloading {url}")
    with urllib.request.urlopen(url) as resp:
        data = json.load(resp)

    required = {"calcCorrectGraphs", "attackElementCorrects", "reinforceTypes",
                "statusSpEffectParams", "scalingTiers", "weapons"}
    missing = required - data.keys()
    if missing:
        raise SystemExit(f"Unexpected format, missing keys: {sorted(missing)}")

    out = Path(args.out) / f"regulation-{args.version}.json"
    out.write_text(json.dumps(data, separators=(",", ":")), encoding="utf-8")
    print(f"Wrote {len(data['weapons'])} weapons to {out}")


if __name__ == "__main__":
    main()
