// erbuild in the browser: Pyodide runs the same Python package as the CLI.
// All game math lives in Python; this file only moves inputs in and results out
// through erbuild.api (JSON in, JSON out).

const PYODIDE = "https://cdn.jsdelivr.net/pyodide/v314.0.7/full/";
const ENEMY_URL =
  "https://docs.google.com/spreadsheets/d/1BVwmKqB8pvuyJkSTGYOM2kAJxFMQ0jVsc6aKYz_Upes/export?format=xlsx";
const STATS = ["str", "dex", "int", "fai", "arc"];
const LABELS = {
  physical: "Physical", magic: "Magic", fire: "Fire", lightning: "Lightning", holy: "Holy",
  poison: "Poison", scarlet_rot: "Scarlet Rot", bleed: "Bleed", frost: "Frost",
  sleep: "Sleep", madness: "Madness", death_blight: "Death Blight",
};

const $ = (id) => document.getElementById(id);
const start = performance.now();
const timings = [];
let py, api;
let weaponsByName = new Map();
let enemiesLoaded = false;

function mark(label, since) {
  timings.push([label, performance.now() - since]);
  $("timings").textContent = timings
    .map(([l, ms]) => `${l} ${ms < 1000 ? `${ms.toFixed(0)} ms` : `${(ms / 1000).toFixed(1)} s`}`)
    .join(" · ");
}

function setStatus(text, isError = false) {
  $("status").textContent = text;
  $("status").classList.toggle("error", isError);
}

function call(method, payload = {}) {
  return JSON.parse(api.call(method, JSON.stringify(payload)));
}

function escapeHtml(s) {
  return String(s).replace(/[&<>"']/g, (c) => `&#${c.charCodeAt(0)};`);
}

// ---------------------------------------------------------------- boot
async function boot() {
  let t = performance.now();
  const { loadPyodide } = await import(`${PYODIDE}pyodide.mjs`);
  py = await loadPyodide({ indexURL: PYODIDE });
  mark("Python", t);

  setStatus("Loading NumPy…");
  t = performance.now();
  await py.loadPackage(["micropip", "numpy"]);
  mark("NumPy", t);

  setStatus("Loading erbuild…");
  t = performance.now();
  const { file } = await (await fetch("dist/wheel.json")).json();
  await py.pyimport("micropip").install(new URL(`dist/${file}`, location.href).href);
  api = py.pyimport("erbuild.api");
  const weapons = call("weapons");
  weaponsByName = new Map(weapons.map((w) => [w.name, w]));
  $("weapon-list").innerHTML = weapons
    .map((w) => `<option value="${escapeHtml(w.name)}">`)
    .join("");
  mark("erbuild", t);

  for (const el of document.querySelectorAll("input, button")) el.disabled = false;
  $("ar-form").removeAttribute("aria-busy");
  setStatus(`Ready in ${((performance.now() - start) / 1000).toFixed(1)} s.`);
  t = performance.now();
  render();
  mark("first result", t);
}

// ---------------------------------------------------------------- AR
function request() {
  const attributes = Object.fromEntries(STATS.map((s) => [s, Number($(s).value) || 1]));
  const payload = {
    weapon: $("weapon").value.trim(),
    attributes,
    upgrade: Number($("upgrade").value),
    two_handing: $("two-handing").checked,
    attack_type: $("attack-type").value,
  };
  const enemy = $("enemy").value.trim();
  if (enemiesLoaded && enemy) {
    payload.enemy = { name: enemy, cycle: $("cycle").value };
    if ($("location").value.trim()) payload.enemy.location = $("location").value.trim();
  }
  return payload;
}

function syncUpgrade() {
  const w = weaponsByName.get($("weapon").value.trim());
  if (!w) return;
  $("upgrade").max = w.max_upgrade;
  if (Number($("upgrade").value) > w.max_upgrade) $("upgrade").value = w.max_upgrade;
}

function render() {
  if (!api) return;
  syncUpgrade();
  const out = call("attack_rating", request());
  const el = $("result");
  el.classList.remove("muted");
  if (out.error) {
    el.innerHTML = `<p class="warn">${escapeHtml(out.error)}</p>`;
    return;
  }
  const rows = Object.entries(out.damage)
    .map(([t, v]) => `<tr><td>${LABELS[t]}</td><td class="num">${v}</td></tr>`)
    .join("");
  const status = Object.entries(out.status)
    .map(([t, v]) => `<tr><td>${LABELS[t]} buildup</td><td class="num">${v}</td></tr>`)
    .join("");
  const scaling = Object.entries(out.scaling).map(([a, g]) => `${a.toUpperCase()} ${g}`).join(", ");
  let html = `<table>${rows}<tr class="total"><td>Total</td><td class="num">${out.total}</td></tr>${status}</table>`;
  html += `<p class="note muted">${escapeHtml(out.weapon)} +${out.upgrade}, ${
    out.two_handing ? "two" : "one"
  }-handed · scaling ${scaling || "none"}</p>`;
  if (out.unmet_requirements.length) {
    html += `<p class="note warn">Requirements not met: ${out.unmet_requirements
      .map((a) => a.toUpperCase())
      .join(", ")}. Affected damage takes a 40% penalty and loses scaling.</p>`;
  }
  if (out.vs_enemy) html += enemyHtml(out.vs_enemy);
  el.innerHTML = html;
}

function enemyHtml(v) {
  const e = v.enemy;
  let html = `<p class="note"><strong>vs ${escapeHtml(e.name)}</strong> (${escapeHtml(e.location)}, ${e.cycle}):
    ${v.total.toFixed(0)} damage per hit`;
  if (v.bleed_proc) {
    html += ` = ${v.direct.toFixed(0)} direct + ${v.bleed_per_hit.toFixed(0)} bleed
      (${v.bleed_proc.toFixed(0)} per proc, every ${v.hits_to_proc} hits)`;
  }
  return html + "</p>";
}

// ---------------------------------------------------------------- enemies
async function loadEnemies() {
  const button = $("load-enemies");
  button.disabled = true;
  button.textContent = "Downloading…";
  let t = performance.now();
  try {
    const response = await fetch(ENEMY_URL);
    if (!response.ok) throw new Error(`download failed (HTTP ${response.status})`);
    const bytes = new Uint8Array(await response.arrayBuffer());
    mark(`enemy download (${(bytes.length / 1e6).toFixed(1)} MB)`, t);
    button.textContent = "Converting…";
    t = performance.now();
    const summary = api.load_enemy_workbook(bytes).toJs({ dict_converter: Object.fromEntries });
    if (summary.error) throw new Error(summary.error);
    $("enemy-list").innerHTML = call("enemy_names")
      .map((n) => `<option value="${escapeHtml(n)}">`)
      .join("");
    mark("enemy convert", t);
    enemiesLoaded = true;
    $("enemy-controls").hidden = false;
    button.textContent = `Loaded ${summary.placements.toLocaleString()} enemy placements`;
    render();
    return summary;
  } catch (err) {
    button.disabled = false;
    button.textContent = "Download enemy data";
    setStatus(`Couldn't load enemy data: ${err.message}`, true);
    throw err;
  }
}

// ---------------------------------------------------------------- wiring
$("ar-form").addEventListener("input", render);
$("ar-form").addEventListener("submit", (e) => e.preventDefault());
for (const id of ["enemy", "cycle", "attack-type", "location"]) {
  $(id).addEventListener("input", render);
  $(id).addEventListener("change", render);
}
$("load-enemies").addEventListener("click", () => loadEnemies().catch(() => {}));

// ?selftest runs a scripted check and writes the results into the page, so the
// prototype can be verified in a headless browser.
async function selftest() {
  const results = { ok: false };
  try {
    results.ar = call("attack_rating", {
      weapon: "Blood Uchigatana", attributes: { str: 12, dex: 40, arc: 50 },
    });
    results.enemies = await loadEnemies();
    results.vs_malenia = call("optimize", {
      weapon: "Blood Uchigatana", starting_class: "samurai", level: 150,
      fixed: { vig: 60 }, enemy: { name: "Malenia, Blade of Miquella [Boss]" },
    });
    results.ok = true;
  } catch (err) {
    results.error = String(err);
  }
  results.timings = Object.fromEntries(timings.map(([l, ms]) => [l, Math.round(ms)]));
  const pre = document.createElement("pre");
  pre.id = "selftest";
  pre.textContent = JSON.stringify(results);
  document.body.append(pre);
  document.title = "selftest done";
}

boot()
  .then(() => (new URLSearchParams(location.search).has("selftest") ? selftest() : null))
  .catch((err) => {
    console.error(err);
    setStatus(`Failed to start: ${err.message}`, true);
  });
