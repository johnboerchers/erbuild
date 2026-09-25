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
import urllib.error
import urllib.request
from pathlib import Path

# HEAD follows the upstream default branch (currently "master"), whatever it's named.
BASE = "https://raw.githubusercontent.com/ThomasJClark/elden-ring-weapon-calculator/HEAD/public"


def main() -> None:
    p = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    p.add_argument("version", help="e.g. vanilla-v1.17")
    p.add_argument("--out", default="src/erbuild/data", help="Output directory")
    args = p.parse_args()

    url = f"{BASE}/regulation-{args.version}.js"
    print(f"Downloading {url}")
    try:
        with urllib.request.urlopen(url, timeout=60) as resp:
            data = json.load(resp)
    except urllib.error.HTTPError as e:
        hint = " Check the version name against the upstream public/ folder." if e.code == 404 else ""
        raise SystemExit(f"Download failed: HTTP {e.code}.{hint}") from None
    except (urllib.error.URLError, TimeoutError) as e:
        raise SystemExit(f"Download failed: {getattr(e, 'reason', e)}") from None
    except json.JSONDecodeError:
        raise SystemExit("Download succeeded but isn't JSON; has the upstream format changed?") from None

    required = {"calcCorrectGraphs", "attackElementCorrects", "reinforceTypes",
                "statusSpEffectParams", "scalingTiers", "weapons"}
    missing = required - data.keys()
    if missing:
        raise SystemExit(f"Unexpected format, missing keys: {sorted(missing)}")

    out = Path(args.out) / f"regulation-{args.version}.json"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(data, separators=(",", ":")), encoding="utf-8")
    print(f"Wrote {len(data['weapons'])} weapons to {out}")


if __name__ == "__main__":
    main()
