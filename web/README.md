# erbuild web

A static page that runs erbuild in the browser with [Pyodide](https://pyodide.org):
the same Python package as the CLI, NumPy included. There's no server and no
JavaScript copy of the game math. `app.js` only passes JSON to and from
[`erbuild.api`](../src/erbuild/api.py).

It has two modes:

- **Optimizer:** pick a weapon, class, level and fixed stats. The page shows the
  best build and a chart of AR against bleed (or other arcane buildup) where you
  can click through every Pareto-optimal build. With an enemy chosen, it finds the
  build with the most damage per hit and compares it with the highest-AR build.
- **Calculator:** AR and damage per hit for a stat line you enter.

The page keeps its state in the URL, so a link reproduces the exact build.

## Run it locally

```bash
python web/build.py              # builds the erbuild wheel into web/dist/
python -m http.server -d web     # then open http://localhost:8000
```

Rebuild the wheel after changing Python code. Opening `index.html` as a file won't
work; it has to be served over HTTP.

## How it works

1. Loads Pyodide and NumPy from the jsDelivr CDN.
2. Installs `dist/erbuild-*.whl` with micropip (`dist/wheel.json` names the file).
3. Calls `erbuild.api.call(method, json)` for every result.

Enemy data isn't hosted here either: the "Download enemy data" button fetches the
community sheet straight from Google in the visitor's browser (Google allows
cross-origin downloads of it), then converts it with the same Python code as
`erbuild enemies update`. The converted data is saved in the browser's IndexedDB,
so later visits load it in about 0.3 s instead of downloading again.

Files: `index.html` (layout), `style.css` (warm dark theme; the chart colors were
checked for lightness, chroma and color-blind separation against the card
surface), `chart.js` (the SVG frontier chart), `app.js` (wiring).

## Deployment

[`.github/workflows/pages.yml`](../.github/workflows/pages.yml) publishes the app to
GitHub Pages on every push to `main`: it runs the tests, builds the wheel with
`web/build.py`, and uploads the `web/` folder. Pages serves static files only, and the
enemy data is never deployed; each visitor's browser downloads it from Google.

## Self-test

Open `http://localhost:8000/?selftest`. After loading, the page reads the
optimizer and calculator results from its own UI, downloads the enemy data and
selects Malenia. It then writes the results and timings as JSON into a hidden
`<pre id="selftest">` element, so a headless browser can check them.

Measured in headless Chrome: ready in about 1.5–2 s (Python ~1 s, NumPy ~0.2 s,
erbuild ~0.7 s). An optimizer run takes about 50 ms and a calculator update a few
milliseconds. The first enemy download takes about 3–7 s (6–7 MB) plus about 4 s to
convert; after that it loads from the browser in about 0.3 s.
