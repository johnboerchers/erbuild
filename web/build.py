"""Build the erbuild wheel the web page installs into Pyodide.

    python web/build.py            # writes web/dist/erbuild-<version>-py3-none-any.whl
    python -m http.server -d web   # then open http://localhost:8000

The page reads web/dist/wheel.json to find the wheel's file name.
"""

from __future__ import annotations

import json
import shutil
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DIST = ROOT / "web" / "dist"


def main() -> None:
    shutil.rmtree(DIST, ignore_errors=True)
    DIST.mkdir(parents=True)
    subprocess.run(
        [sys.executable, "-m", "pip", "wheel", str(ROOT), "--no-deps", "-w", str(DIST), "-q"],
        check=True,
    )
    wheels = list(DIST.glob("erbuild-*.whl"))
    if len(wheels) != 1:
        raise SystemExit(f"Expected one wheel in {DIST}, found {wheels}")
    (DIST / "wheel.json").write_text(json.dumps({"file": wheels[0].name}))
    print(f"Built {wheels[0].relative_to(ROOT)}")


if __name__ == "__main__":
    main()
