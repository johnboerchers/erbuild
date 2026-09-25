// The AR vs. buildup frontier chart: one series, so no legend box; the selected
// build is direct-labeled, the rest are reachable by hover, arrow keys and the table.

const SVG = "http://www.w3.org/2000/svg";

function el(name, attrs = {}, parent) {
  const node = document.createElementNS(SVG, name);
  for (const [k, v] of Object.entries(attrs)) node.setAttribute(k, v);
  if (parent) parent.append(node);
  return node;
}

function niceTicks(min, max, count = 5) {
  if (min === max) { min -= 1; max += 1; }
  const raw = (max - min) / count;
  const mag = 10 ** Math.floor(Math.log10(raw));
  const step = [1, 2, 2.5, 5, 10].map((m) => m * mag).find((s) => s >= raw);
  const lo = Math.floor(min / step) * step;
  const hi = Math.ceil(max / step) * step;
  const ticks = [];
  for (let v = lo; v <= hi + step / 2; v += step) ticks.push(Math.round(v * 1e6) / 1e6);
  return ticks;
}

/**
 * @param {HTMLElement} container
 * @param {{points: {x:number, y:number, stats:string}[], selected:number, marked:number|null,
 *          xLabel:string, yLabel:string, markedLabel:string, onSelect:(i:number)=>void}} opts
 */
export function renderFrontier(container, opts) {
  const { points, selected, marked, xLabel, yLabel, markedLabel, onSelect } = opts;
  container.replaceChildren();
  const width = Math.max(280, container.clientWidth);
  const height = width < 520 ? 240 : 300;
  const m = { top: 28, right: 18, bottom: 42, left: 48 };
  const iw = width - m.left - m.right;
  const ih = height - m.top - m.bottom;

  const xs = points.map((p) => p.x);
  const ys = points.map((p) => p.y);
  const xt = niceTicks(Math.min(...xs), Math.max(...xs), width < 520 ? 4 : 6);
  const yt = niceTicks(Math.min(...ys), Math.max(...ys), 5);
  const x = (v) => m.left + ((v - xt[0]) / (xt.at(-1) - xt[0])) * iw;
  const y = (v) => m.top + ih - ((v - yt[0]) / (yt.at(-1) - yt[0])) * ih;

  const svg = el("svg", {
    viewBox: `0 0 ${width} ${height}`,
    role: "img",
    tabindex: "0",
    "aria-label": `${yLabel} against ${xLabel} for ${points.length} Pareto-optimal builds. ` +
      "Use the left and right arrow keys to select a build.",
  }, container);

  const grid = el("g", { class: "grid" }, svg);
  const axis = el("g", { class: "axis" }, svg);
  for (const t of yt) {
    el("line", { x1: m.left, x2: m.left + iw, y1: y(t), y2: y(t) }, grid);
    const label = el("text", { x: m.left - 10, y: y(t) + 4, "text-anchor": "end" }, axis);
    label.textContent = t.toLocaleString();
  }
  for (const t of xt) {
    const label = el("text", { x: x(t), y: m.top + ih + 18, "text-anchor": "middle" }, axis);
    label.textContent = t.toLocaleString();
  }
  el("text", { class: "axis-title", x: m.left + iw, y: height - 4, "text-anchor": "end" }, svg)
    .textContent = `${xLabel} →`;
  el("text", { class: "axis-title", x: m.left - 40, y: 12 }, svg).textContent = `↑ ${yLabel}`;

  const path = points.map((p, i) => `${i ? "L" : "M"}${x(p.x).toFixed(1)},${y(p.y).toFixed(1)}`).join("");
  if (points.length > 1) {
    el("path", {
      class: "area",
      d: `${path}L${x(points.at(-1).x).toFixed(1)},${m.top + ih}L${x(points[0].x).toFixed(1)},${m.top + ih}Z`,
    }, svg);
    el("path", { class: "series", d: path }, svg);
  }

  const hoverLine = el("line", { class: "hover-line", y1: m.top, y2: m.top + ih, visibility: "hidden" }, svg);

  points.forEach((p, i) => {
    if (i === selected) return;
    el("circle", { class: "pt", cx: x(p.x), cy: y(p.y), r: 4 }, svg);
  });
  if (marked != null && points[marked]) {
    el("circle", { class: "enemy-pt", cx: x(points[marked].x), cy: y(points[marked].y), r: 10 }, svg);
  }
  const sp = points[selected];
  if (sp) {
    el("circle", { class: "halo", cx: x(sp.x), cy: y(sp.y), r: 11 }, svg);
    el("circle", { class: "pt selected", cx: x(sp.x), cy: y(sp.y), r: 6 }, svg);
    // Direct label for the selected build only; flip sides near the edges.
    const px = x(sp.x);
    const anchor = px > m.left + iw * 0.7 ? "end" : px < m.left + iw * 0.3 ? "start" : "middle";
    const dx = anchor === "end" ? -8 : anchor === "start" ? 8 : 0;
    const above = y(sp.y) - m.top > 34;
    const ly = above ? y(sp.y) - 18 : y(sp.y) + 30;
    el("text", { class: "label", x: px + dx, y: ly, "text-anchor": anchor }, svg)
      .textContent = `${yLabel} ${sp.y.toLocaleString()} · ${xLabel} ${Math.round(sp.x).toLocaleString()}`;
  }

  // Hover layer: the whole plot is the hit target; the nearest build wins.
  const tip = document.createElement("div");
  tip.className = "tooltip";
  tip.hidden = true;
  container.append(tip);
  const hit = el("rect", {
    x: m.left - 12, y: m.top - 12, width: iw + 24, height: ih + 24, fill: "transparent",
  }, svg);

  function nearest(evt) {
    const rect = svg.getBoundingClientRect();
    const scale = width / rect.width;
    const mx = (evt.clientX - rect.left) * scale;
    const my = (evt.clientY - rect.top) * scale;
    let best = 0;
    let bestD = Infinity;
    points.forEach((p, i) => {
      const d = (x(p.x) - mx) ** 2 + ((y(p.y) - my) ** 2) * 0.25;
      if (d < bestD) { bestD = d; best = i; }
    });
    return { i: best, scale };
  }

  function showTip(i, scale) {
    const p = points[i];
    tip.replaceChildren();
    const strong = document.createElement("strong");
    strong.textContent = `${yLabel} ${p.y.toLocaleString()}`;
    const second = document.createElement("div");
    second.textContent = `${xLabel} ${Math.round(p.x).toLocaleString()}`;
    const third = document.createElement("div");
    third.className = "t-sub";
    third.textContent = p.stats;
    tip.append(strong, second, third);
    if (i === marked && markedLabel) {
      const fourth = document.createElement("div");
      fourth.className = "t-sub";
      fourth.textContent = markedLabel;
      tip.append(fourth);
    }
    tip.style.left = `${x(p.x) / scale}px`;
    tip.style.top = `${y(p.y) / scale}px`;
    tip.hidden = false;
    hoverLine.setAttribute("x1", x(p.x));
    hoverLine.setAttribute("x2", x(p.x));
    hoverLine.setAttribute("visibility", "visible");
  }

  hit.addEventListener("pointermove", (evt) => {
    const { i, scale } = nearest(evt);
    showTip(i, scale);
  });
  hit.addEventListener("pointerleave", () => {
    tip.hidden = true;
    hoverLine.setAttribute("visibility", "hidden");
  });
  hit.addEventListener("click", (evt) => onSelect(nearest(evt).i));
  hit.style.cursor = "pointer";
  svg.addEventListener("keydown", (evt) => {
    if (evt.key === "ArrowLeft" || evt.key === "ArrowRight") {
      evt.preventDefault();
      const next = Math.min(points.length - 1, Math.max(0, selected + (evt.key === "ArrowRight" ? 1 : -1)));
      if (next !== selected) onSelect(next, { focus: true });
    }
  });
  return svg;
}
