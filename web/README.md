# erbuild web (prototype)

A static page that runs erbuild in the browser with [Pyodide](https://pyodide.org):
the same Python package as the CLI, NumPy included. There's no server and no
JavaScript copy of the game math. `app.js` only passes JSON to and from
[`erbuild.api`](../src/erbuild/api.py).

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
`erbuild enemies update`.

## Self-test

Open `http://localhost:8000/?selftest`. After loading, the page computes an AR,
downloads the enemy data and optimizes against Malenia. It then writes the results
and timings as JSON into a `<pre id="selftest">` element, so a headless browser can
check them.

Measured in headless Chrome: ready in about 1.5–2 s (Python ~1 s, NumPy ~0.2 s,
erbuild ~0.7 s). Each AR update takes a few milliseconds. The enemy data takes about
4–6 s to download (6–7 MB) and about 4 s to convert.
