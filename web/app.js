// erbuild in the browser. Pyodide runs the same Python package as the CLI; this file
// only moves inputs in and results out through erbuild.api (JSON in, JSON out).
// No game math lives here.

import { renderFrontier } from "./chart.js";

const PYODIDE = "https://cdn.jsdelivr.net/pyodide/v314.0.7/full/";
const ENEMY_URL =
  "https://docs.google.com/spreadsheets/d/1BVwmKqB8pvuyJkSTGYOM2kAJxFMQ0jVsc6aKYz_Upes/export?format=xlsx";
const ALL = ["vig", "mnd", "end", "str", "dex", "int", "fai", "arc"];
const DAMAGE_STATS = ["str", "dex", "int", "fai", "arc"];
const FIXABLE = ["vig", "mnd", "end"];
const LABELS = {
  physical: "Physical", magic: "Magic", fire: "Fire", lightning: "Lightning", holy: "Holy",
  poison: "Poison", scarlet_rot: "Scarlet rot", bleed: "Bleed", frost: "Frost",
  sleep: "Sleep", madness: "Madness", death_blight: "Death blight",
};

const $ = (id) => document.getElementById(id);
const start = performance.now();
const timings = [];
let py, api;
let weaponsByName = new Map();
let classesByName = new Map();
let enemiesLoaded = false;
let selected = null;      // index into the current frontier, or null for "the best"
let lastFrontierKey = "";

// ---------------------------------------------------------------- tiny DOM helper
function h(tag, props = {}, ...children) {
  const node = document.createElement(tag);
  for (const [k, v] of Object.entries(props)) {
    if (v == null || v === false) continue;
    if (k === "class") node.className = v;
    else if (k === "style") node.style.cssText = v;
    else if (k.startsWith("on")) node.addEventListener(k.slice(2), v);
    else node.setAttribute(k, v === true ? "" : v);
  }
  for (const c of children.flat()) {
    if (c == null || c === false) continue;
    node.append(c instanceof Node ? c : document.createTextNode(String(c)));
  }
  return node;
}

// replaceChildren would print "null" for skipped optional parts, so drop them first.
function fill(target, children) {
  target.replaceChildren(...children.flat().filter((c) => c != null && c !== false));
}

const fmt = (n) => Math.round(n).toLocaleString();
const pct = (n) => `${(n * 100).toFixed(1)}%`;

function call(method, payload = {}) {
  return JSON.parse(api.call(method, JSON.stringify(payload)));
}

function mark(label, since) {
  timings.push([label, performance.now() - since]);
  $("timings").textContent = timings
    .map(([l, ms]) => `${l} ${ms < 1000 ? `${ms.toFixed(0)} ms` : `${(ms / 1000).toFixed(1)} s`}`)
    .join(" · ");
}

function setStatus(text, state = "") {
  $("status-text").textContent = text;
  $("status").className = `status-pill ${state}`;
}

// ---------------------------------------------------------------- state <-> form <-> URL
const HASH_FIELDS = {
  w: "weapon", u: "upgrade", c: "class", l: "level", e: "enemy", cy: "cycle",
  at: "attack-type", mv: "mv", loc: "location",
  ...Object.fromEntries(FIXABLE.map((a) => [a, `fix-${a}`])),
  ...Object.fromEntries(DAMAGE_STATS.map((a) => [`min${a}`, `min-${a}`])),
  ...Object.fromEntries(DAMAGE_STATS.map((a) => [`c${a}`, a])),
};

function mode() {
  return $("tab-calculator").getAttribute("aria-selected") === "true" ? "calculator" : "optimizer";
}

function twoHanding() {
  return document.querySelector('input[name="grip"]:checked').value === "two";
}

function writeHash() {
  const params = new URLSearchParams();
  params.set("m", mode());
  if (twoHanding()) params.set("g", "2");
  for (const [key, id] of Object.entries(HASH_FIELDS)) {
    const v = $(id).value.trim();
    if (v !== "") params.set(key, v);
  }
  history.replaceState(null, "", `#${params}`);
}

function readHash() {
  const params = new URLSearchParams(location.hash.slice(1));
  if (!params.size) return;
  for (const [key, id] of Object.entries(HASH_FIELDS)) {
    if (params.has(key)) $(id).value = params.get(key);
    else if (id.startsWith("fix-") || id.startsWith("min-")) $(id).value = "";
  }
  document.querySelector(`input[name="grip"][value="${params.get("g") === "2" ? "two" : "one"}"]`).checked = true;
  setMode(params.get("m") === "calculator" ? "calculator" : "optimizer", false);
}

function numberOrNull(id) {
  const v = $(id).value.trim();
  return v === "" ? null : Number(v);
}

function enemySpec() {
  const name = $("enemy").value.trim();
  if (!enemiesLoaded || !name) return null;
  const spec = { name, cycle: $("cycle").value };
  if ($("location").value.trim()) spec.location = $("location").value.trim();
  return spec;
}

function enemyOptions() {
  return { motion_value: Number($("mv").value) || 100, attack_type: $("attack-type").value };
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
  weaponsByName = new Map(weapons.map((w) => [w.name.toLowerCase(), w]));
  $("weapon-list").replaceChildren(...weapons.map((w) => h("option", { value: w.name })));
  const classes = call("classes");
  classesByName = new Map(classes.map((c) => [c.name.toLowerCase(), c]));
  $("class").replaceChildren(...classes.map((c) =>
    h("option", { value: c.name.toLowerCase() }, c.name)));
  $("class").value = "samurai";
  mark("erbuild", t);

  readHash();
  for (const node of $("controls").querySelectorAll("input, select, button")) node.disabled = false;
  $("controls").removeAttribute("aria-busy");
  setStatus(`Ready in ${((performance.now() - start) / 1000).toFixed(1)} s`, "ready");
  t = performance.now();
  render();
  mark("first result", t);

  // Reuse enemy data from a previous visit, if the browser kept it.
  loadCachedEnemies().catch(() => {});
}

// ---------------------------------------------------------------- rendering
let pending = 0;
function schedule() {
  clearTimeout(pending);
  pending = setTimeout(() => { writeHash(); render(); }, 80);
}

function render() {
  if (!api) return;
  syncWeapon();
  for (const node of document.querySelectorAll("[data-show]")) node.hidden = node.dataset.show !== mode();
  $("view-optimizer").hidden = mode() !== "optimizer";
  $("view-calculator").hidden = mode() !== "calculator";
  if (mode() === "optimizer") renderOptimizer();
  else renderCalculator();
}

function syncWeapon() {
  const w = weaponsByName.get($("weapon").value.trim().toLowerCase());
  const max = w ? w.max_upgrade : 25;
  $("upgrade").max = max;
  if (Number($("upgrade").value) > max) $("upgrade").value = max;
  $("upgrade-out").textContent = `+${$("upgrade").value}`;
}

function context(out) {
  return `${out.weapon} +${out.upgrade} · ${twoHanding() ? "two" : "one"}-handed`;
}

function errorCard(target, eyebrow, message) {
  target.replaceChildren(h("p", { class: "eyebrow" }, eyebrow), h("p", { class: "warning" }, message));
  target.className = "card result-card";
}

// ---- optimizer
function optimizerRequest() {
  const fixed = {};
  for (const a of FIXABLE) {
    const v = numberOrNull(`fix-${a}`);
    if (v != null) fixed[a] = v;
  }
  const minimum = {};
  for (const a of DAMAGE_STATS) {
    const v = numberOrNull(`min-${a}`);
    if (v != null) minimum[a] = v;
  }
  return {
    weapon: $("weapon").value.trim(),
    starting_class: $("class").value,
    level: Number($("level").value),
    upgrade: Number($("upgrade").value),
    two_handing: twoHanding(),
    fixed,
    minimum,
  };
}

function renderOptimizer() {
  const req = optimizerRequest();
  const key = JSON.stringify([req, enemySpec(), enemyOptions()]);
  if (key !== lastFrontierKey) { selected = null; lastFrontierKey = key; }
  const summary = $("opt-summary");
  const out = call("optimize", req);
  if (out.error) {
    errorCard(summary, "Best build", out.error);
    $("opt-chart-card").hidden = true;
    return;
  }
  const frontier = out.frontier;
  const bestIndex = frontier.findIndex((b) => sameStats(b.attributes, out.best.attributes));

  const enemy = enemySpec();
  let vs = null;
  let enemyError = null;
  let marked = null;
  if (enemy) {
    vs = call("optimize", { ...req, enemy, ...enemyOptions() });
    if (vs.error) { enemyError = vs.error; vs = null; }
    else marked = frontier.findIndex((b) => sameStats(b.attributes, vs.best.attributes));
    if (marked === -1) marked = null;
  }

  const defaultIndex = vs ? marked : bestIndex;
  const index = selected ?? defaultIndex;
  const fixedStats = new Set(Object.keys(req.fixed));

  if (vs && (index == null || index === marked)) {
    renderEnemyBest(summary, out, vs, fixedStats);
  } else {
    const build = frontier[index] ?? out.best;
    renderFrontierBuild(summary, out, build, index === bestIndex, fixedStats, enemy);
  }
  if (enemyError) summary.append(h("p", { class: "warning" }, `Enemy: ${enemyError}`));
  renderChart(out, index ?? bestIndex, marked, vs);
}

function sameStats(a, b) {
  return ALL.every((s) => a[s] === b[s]);
}

function statBars(attributes, base, fixedStats) {
  const rows = ALL.map((a) => {
    const b = Math.min(base[a], attributes[a]);
    const added = attributes[a] - b;
    const isFixed = fixedStats.has(a);
    return h("div", { class: `stat-bar${isFixed ? " fixed" : ""}` },
      h("span", { class: "name" }, a.toUpperCase()),
      h("span", { class: "track", "aria-hidden": "true" },
        h("span", { class: "base", style: `width:${(b / 99) * 100}%` }),
        added > 0 && h("span", { class: "added", style: `width:calc(${(added / 99) * 100}% - 2px)` })),
      h("span", { class: "value" }, String(attributes[a]),
        added > 0 && h("small", {}, isFixed ? "fixed" : `+${added}`)));
  });
  return [
    h("div", { class: "stat-bars" }, rows),
    h("p", { class: "legend" },
      h("span", {}, h("i", { style: "background:var(--bronze)" }), "Class base"),
      h("span", {}, h("i", { style: "background:var(--gold)" }), "Points spent by the optimizer"),
      fixedStats.size > 0 && h("span", {}, h("i", { style: "background:#6f6152" }), "Fixed by you")),
  ];
}

function chipsFor(build, statusTypes) {
  const chips = [];
  for (const t of statusTypes) {
    if (build.status[t] != null) chips.push(h("li", {}, `${LABELS[t]} `, h("strong", {}, fmt(build.status[t]))));
  }
  chips.push(h("li", {}, "Free points ", h("strong", {}, String(build.free_points))));
  return h("ul", { class: "chips" }, chips);
}

function unmetWarning(build) {
  if (!build.unmet_requirements.length) return null;
  const stats = build.unmet_requirements.map((a) => a.toUpperCase()).join(", ");
  return h("p", { class: "warning" },
    `Requirement deliberately left unmet: ${stats}. That damage takes a 40% penalty, and it's still the best option here.`);
}

function renderFrontierBuild(target, out, build, isBest, fixedStats, enemy) {
  const children = [
    h("p", { class: "eyebrow" }, isBest ? "Highest attack rating" : "Selected build"),
    h("p", { class: "hero-number" }, h("strong", {}, fmt(build.ar)), h("span", {}, "AR")),
    h("p", { class: "subline" }, `${context(out)} · ${out.class}, level ${out.level}`),
    chipsFor(build, out.status_types),
    unmetWarning(build),
  ];
  if (enemy) {
    const v = call("attack_rating", {
      weapon: out.weapon, attributes: build.attributes, upgrade: out.upgrade,
      two_handing: twoHanding(), enemy, ...enemyOptions(),
    });
    if (!v.error && v.vs_enemy) {
      children.push(h("dl", { class: "rows" }, damageRows(v.vs_enemy, `Damage per hit vs ${v.vs_enemy.enemy.name}`)));
    }
  }
  children.push(...statBars(build.attributes, out.class_stats, fixedStats));
  fill(target, children);
  target.className = "card result-card";
}

function damageRows(d, title) {
  const rows = title ? [h("div", {}, h("dt", {}, title), h("dd", {}, fmt(d.total)))] : [];
  rows.push(h("div", { class: "sub" }, h("dt", {}, "Direct damage"), h("dd", {}, fmt(d.direct))));
  if (d.bleed_proc) {
    rows.push(h("div", { class: "sub" },
      h("dt", {}, `Bleed: ${fmt(d.bleed_proc)} per proc, every ${d.hits_to_proc} hits`),
      h("dd", {}, fmt(d.bleed_per_hit))));
  }
  return rows;
}

function renderEnemyBest(target, out, vs, fixedStats) {
  const best = vs.best;
  const ref = vs.highest_ar;
  const same = sameStats(best.attributes, ref.attributes);
  const gain = ref.damage.total ? best.damage.total / ref.damage.total - 1 : 0;
  const e = vs.enemy;
  const children = [
    h("p", { class: "eyebrow" }, `Most damage vs ${e.name}`),
    h("p", { class: "hero-number" }, h("strong", {}, fmt(best.damage.total)), h("span", {}, "per hit")),
    h("p", { class: "subline" },
      `${context(out)} · ${out.class}, level ${out.level} · ${e.location}, ${e.cycle}`),
    h("dl", { class: "rows" },
      h("div", {}, h("dt", {}, "Attack rating"), h("dd", {}, fmt(best.ar))),
      damageRows(best.damage, null)),
    h("div", { class: "compare" },
      h("div", {},
        h("h3", {}, "This build"),
        h("p", { class: "big" }, fmt(best.damage.total)),
        h("p", {}, `AR ${fmt(best.ar)}`)),
      h("div", {},
        h("h3", {}, "Highest-AR build"),
        h("p", { class: "big" }, fmt(ref.damage.total)),
        h("p", {}, same ? "The same build" :
          gain >= 0.0005 ? `AR ${fmt(ref.ar)} · this build does ${pct(gain)} more` :
          `AR ${fmt(ref.ar)} · practically the same damage`))),
    unmetWarning(best),
    best.free_points ? h("ul", { class: "chips" }, h("li", {}, "Free points ", h("strong", {}, String(best.free_points)))) : null,
  ];
  children.push(...statBars(best.attributes, out.class_stats, fixedStats));
  if (best.damage.bleed_proc) {
    children.push(h("p", { class: "hint small" },
      "Bleed counts hits to the first proc; the game raises resistance after each one. See the README."));
  }
  fill(target, children);
  target.className = "card result-card";
}

function renderChart(out, index, marked, vs) {
  const card = $("opt-chart-card");
  const statusType = out.status_types[0];
  if (out.frontier.length < 2 || !statusType) {
    card.hidden = true;
    return;
  }
  card.hidden = false;
  const label = LABELS[statusType];
  $("chart-title").textContent = `AR vs. ${label.toLowerCase()}`;
  $("chart-sub").textContent = vs
    ? `Each point is the highest AR possible at that ${label.toLowerCase()} buildup. The ember ring marks the best build against ${vs.enemy.name}.`
    : `Each point is the highest AR possible at that ${label.toLowerCase()} buildup. Click a point to inspect the build.`;
  const points = out.frontier.map((b) => ({
    x: b.raw_status[statusType] ?? 0,
    y: b.ar,
    stats: DAMAGE_STATS.filter((a) => b.attributes[a] > out.class_stats[a])
      .map((a) => `${a.toUpperCase()} ${b.attributes[a]}`).join(" · ") || "Class base stats",
  }));
  renderFrontier($("chart"), {
    points,
    selected: index,
    marked,
    xLabel: label,
    yLabel: "AR",
    markedLabel: vs ? `Best vs ${vs.enemy.name}` : "",
    onSelect: (i, { focus } = {}) => {
      selected = i;
      renderOptimizer();
      if (focus) $("chart").querySelector("svg")?.focus();
    },
  });
  renderTable(out, statusType, index);
}

function renderTable(out, statusType, index) {
  const head = h("tr", {}, ["AR", LABELS[statusType], ...DAMAGE_STATS.map((a) => a.toUpperCase()), "Free"]
    .map((c) => h("th", { scope: "col" }, c)));
  const rows = out.frontier.map((b, i) => h("tr", {
    class: i === index ? "selected" : null,
    tabindex: "0",
    onclick: () => { selected = i; renderOptimizer(); },
    onkeydown: (evt) => { if (evt.key === "Enter") { selected = i; renderOptimizer(); } },
  },
  h("td", {}, fmt(b.ar)), h("td", {}, fmt(b.status[statusType] ?? 0)),
  ...DAMAGE_STATS.map((a) => h("td", {}, String(b.attributes[a]))),
  h("td", {}, String(b.free_points))));
  $("frontier-table").replaceChildren(h("table", {}, h("thead", {}, head), h("tbody", {}, rows)));
}

// ---- calculator
function renderCalculator() {
  const attributes = Object.fromEntries(DAMAGE_STATS.map((a) => [a, Number($(a).value) || 1]));
  const enemy = enemySpec();
  const out = call("attack_rating", {
    weapon: $("weapon").value.trim(),
    attributes,
    upgrade: Number($("upgrade").value),
    two_handing: twoHanding(),
    ...(enemy ? { enemy, ...enemyOptions() } : {}),
  });
  const target = $("calc-summary");
  if (out.error) { errorCard(target, "Attack rating", out.error); return; }
  const rows = Object.entries(out.damage)
    .map(([t, v]) => h("div", {}, h("dt", {}, LABELS[t]), h("dd", {}, fmt(v))));
  for (const [t, v] of Object.entries(out.status)) {
    rows.push(h("div", {}, h("dt", {}, `${LABELS[t]} buildup`), h("dd", {}, fmt(v))));
  }
  const scaling = Object.entries(out.scaling);
  const children = [
    h("p", { class: "eyebrow" }, "Attack rating"),
    h("p", { class: "hero-number" }, h("strong", {}, fmt(out.total)), h("span", {}, "AR")),
    h("p", { class: "subline" }, context(out)),
    h("dl", { class: "rows" }, rows),
    h("ul", { class: "chips" }, scaling.length
      ? scaling.map(([a, g]) => h("li", {}, `${a.toUpperCase()} scaling `, h("strong", {}, g)))
      : h("li", {}, "No attribute scaling")),
  ];
  if (out.unmet_requirements.length) {
    children.push(h("p", { class: "warning" },
      `Requirements not met: ${out.unmet_requirements.map((a) => a.toUpperCase()).join(", ")}. ` +
      "Affected damage takes a 40% penalty and loses its scaling."));
  }
  if (enemy) {
    if (out.vs_enemy) {
      const e = out.vs_enemy.enemy;
      children.push(h("hr", { class: "divider" }),
        h("p", { class: "eyebrow" }, `vs ${e.name}`),
        h("p", { class: "subline" }, `${e.location}, ${e.cycle} · MV ${enemyOptions().motion_value}, ${enemyOptions().attack_type} attack`),
        h("dl", { class: "rows" }, damageRows(out.vs_enemy, "Damage per hit")));
    }
  }
  fill(target, children);
  target.className = "card result-card";
}

// ---------------------------------------------------------------- enemy data
function idb() {
  return new Promise((resolve, reject) => {
    const req = indexedDB.open("erbuild", 1);
    req.onupgradeneeded = () => req.result.createObjectStore("kv");
    req.onsuccess = () => resolve(req.result);
    req.onerror = () => reject(req.error);
  });
}

async function idbGet(key) {
  const db = await idb();
  return new Promise((resolve, reject) => {
    const req = db.transaction("kv").objectStore("kv").get(key);
    req.onsuccess = () => resolve(req.result);
    req.onerror = () => reject(req.error);
  });
}

async function idbSet(key, value) {
  const db = await idb();
  return new Promise((resolve, reject) => {
    const tx = db.transaction("kv", "readwrite");
    tx.objectStore("kv").put(value, key);
    tx.oncomplete = resolve;
    tx.onerror = () => reject(tx.error);
  });
}

function enemiesReady(summary, note) {
  $("enemy-list").replaceChildren(...call("enemy_names").map((n) => h("option", { value: n })));
  enemiesLoaded = true;
  $("enemy-controls").hidden = false;
  const button = $("load-enemies");
  button.disabled = false;
  button.classList.add("done");
  button.textContent = `${summary.placements.toLocaleString()} enemy placements loaded · re-download`;
  $("enemy-cache-note").textContent = note;
  render();
}

async function loadCachedEnemies() {
  const cached = await idbGet("enemies");
  if (!cached?.text) return;
  const t = performance.now();
  const summary = api.load_enemy_data(cached.text).toJs({ dict_converter: Object.fromEntries });
  if (summary.error) return;
  mark("enemy data (cached)", t);
  enemiesReady(summary, `Saved in this browser from a download on ${cached.saved}.`);
}

async function downloadEnemies() {
  const button = $("load-enemies");
  button.disabled = true;
  button.textContent = "Downloading from Google…";
  let t = performance.now();
  try {
    const response = await fetch(ENEMY_URL);
    if (!response.ok) throw new Error(`download failed (HTTP ${response.status})`);
    const bytes = new Uint8Array(await response.arrayBuffer());
    mark(`enemy download (${(bytes.length / 1e6).toFixed(1)} MB)`, t);
    button.textContent = "Converting…";
    await new Promise((r) => setTimeout(r, 30)); // let the label paint before Python blocks
    t = performance.now();
    const summary = api.load_enemy_workbook(bytes).toJs({ dict_converter: Object.fromEntries });
    if (summary.error) throw new Error(summary.error);
    mark("enemy convert", t);
    const saved = new Date().toLocaleDateString(undefined, { year: "numeric", month: "short", day: "numeric" });
    try {
      await idbSet("enemies", { text: api.export_enemy_data(), saved });
    } catch { /* storage unavailable (private mode, quota): just skip caching */ }
    enemiesReady(summary, `Downloaded ${saved}. Saved in this browser for next time.`);
    return summary;
  } catch (err) {
    button.disabled = false;
    button.classList.remove("done");
    button.textContent = "Download enemy data";
    setStatus(`Couldn't load enemy data: ${err.message}`, "error");
    throw err;
  }
}

// ---------------------------------------------------------------- wiring
function setMode(next, rerender = true) {
  for (const tab of document.querySelectorAll(".tabs button")) {
    tab.setAttribute("aria-selected", String(tab.dataset.mode === next));
  }
  if (rerender) { writeHash(); render(); }
}

for (const tab of document.querySelectorAll(".tabs button")) {
  tab.addEventListener("click", () => setMode(tab.dataset.mode));
}
$("controls").addEventListener("input", schedule);
$("controls").addEventListener("change", schedule);
$("controls").addEventListener("submit", (e) => e.preventDefault());
$("load-enemies").addEventListener("click", () => downloadEnemies().catch(() => {}));
$("toggle-table").addEventListener("click", () => {
  const table = $("frontier-table");
  table.hidden = !table.hidden;
  $("toggle-table").setAttribute("aria-expanded", String(!table.hidden));
  $("toggle-table").textContent = table.hidden ? "Show table" : "Hide table";
});
new ResizeObserver(() => { if (api && mode() === "optimizer") renderOptimizer(); }).observe($("chart"));

// ?selftest runs a scripted check and writes the results into the page, so the app
// can be verified in a headless browser.
async function selftest() {
  const results = { ok: false };
  const text = (sel) => document.querySelector(sel)?.textContent.trim();
  try {
    results.optimizer_ar = text("#opt-summary .hero-number strong");
    results.chart_points = document.querySelectorAll("#chart circle.pt").length;
    setMode("calculator");
    results.calculator_ar = text("#calc-summary .hero-number strong");
    setMode("optimizer");
    results.enemies = await downloadEnemies();
    $("enemy").value = "Malenia, Blade of Miquella [Boss]";
    render();
    results.vs_malenia = text("#opt-summary .hero-number strong");
    results.vs_malenia_eyebrow = text("#opt-summary .eyebrow");
    results.ok = true;
  } catch (err) {
    results.error = String(err);
  }
  results.timings = Object.fromEntries(timings.map(([l, ms]) => [l, Math.round(ms)]));
  document.body.append(h("pre", { id: "selftest", hidden: true }, JSON.stringify(results)));
  document.title = "selftest done";
}

boot()
  .then(() => (new URLSearchParams(location.search).has("selftest") ? selftest() : null))
  .catch((err) => {
    console.error(err);
    setStatus(`Failed to start: ${err.message}`, "error");
  });
