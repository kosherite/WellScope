/* WellScope: every well in the WCSB on one map. MapLibre + PMTiles on static hosting; no server, no account. */
"use strict";

const $ = (s, el = document) => el.querySelector(s);
const esc = (s) => String(s ?? "").replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
const css = (v) => getComputedStyle(document.documentElement).getPropertyValue(v).trim();
const PROV = { AB: "Alberta", SK: "Saskatchewan", BC: "British Columbia", MB: "Manitoba" };
const SOURCE = { AB: "AER ST37 well list and Petrinex", SK: "Petrinex Saskatchewan public data", BC: "BC Energy Regulator", MB: "Manitoba Petroleum Branch" };
const n = (v, d = 0) => v == null || !isFinite(v) ? "–" : Number(v).toLocaleString("en-CA", { maximumFractionDigits: d, minimumFractionDigits: d });
const dark = () => document.documentElement.dataset.theme === "dark" || (document.documentElement.dataset.theme !== "light" && matchMedia("(prefers-color-scheme: dark)").matches);

let META = null, OPS = [], map, selected = null, opFilter = null;
const hidden = new Set();
const cache = new Map();
const getJSON = (p) => { if (!cache.has(p)) cache.set(p, fetch("data/" + p).then((r) => { if (!r.ok) throw new Error(r.status); return r.json(); })); return cache.get(p); };

// ------------------------------------------------------------------ well symbols (drawn once, used on the map, legend and panel)
const SYM = ["oil", "gas", "oil_susp", "gas_susp", "aband", "dry", "service", "pre", "other"];
const SYM_COLOR = () => ({ oil: css("--oil"), gas: css("--gas"), oil_susp: css("--oil"), gas_susp: css("--gas"), aband: css("--aband"),
  dry: css("--aband"), service: css("--svc"), pre: css("--pre"), other: css("--aband") });
const ICONS = {};
function drawIcon(kind, px = 48) {
  const c = document.createElement("canvas"); c.width = c.height = px;
  const g = c.getContext("2d"), m = px / 2, r = px * 0.25, col = SYM_COLOR()[kind], halo = dark() ? "#111" : "#fff";
  g.lineCap = "round";
  const circle = (fill, stroke, w = px * 0.07) => { g.beginPath(); g.arc(m, m, r, 0, Math.PI * 2); if (fill) { g.fillStyle = fill; g.fill(); } if (stroke) { g.lineWidth = w; g.strokeStyle = stroke; g.stroke(); } };
  const rays = (n, len) => { g.lineWidth = px * 0.07; g.strokeStyle = col; for (let i = 0; i < n; i++) { const a = i * Math.PI * 2 / n; g.beginPath(); g.moveTo(m + Math.cos(a) * r * 1.15, m + Math.sin(a) * r * 1.15); g.lineTo(m + Math.cos(a) * (r + len), m + Math.sin(a) * (r + len)); g.stroke(); } };
  const cross = (ext) => { g.lineWidth = px * 0.07; g.strokeStyle = col; const k = r * ext; g.beginPath(); g.moveTo(m - k, m - k); g.lineTo(m + k, m + k); g.moveTo(m + k, m - k); g.lineTo(m - k, m + k); g.stroke(); };
  switch (kind) {
    case "oil": circle(col, halo, px * 0.05); break;
    case "gas": rays(8, px * 0.13); circle(col, halo, px * 0.05); break;
    case "oil_susp": circle(halo, col, px * 0.09); break;
    case "gas_susp": rays(8, px * 0.13); circle(halo, col, px * 0.09); break;
    case "aband": circle(halo, col); cross(0.72); break;
    case "dry": rays(4, px * 0.14); circle(halo, col); cross(0.72); break;
    case "service": g.beginPath(); g.moveTo(m, m - r * 1.25); g.lineTo(m + r * 1.15, m + r * 0.85); g.lineTo(m - r * 1.15, m + r * 0.85); g.closePath(); g.fillStyle = col; g.fill(); g.lineWidth = px * 0.05; g.strokeStyle = halo; g.stroke(); break;
    case "pre": circle(halo, col, px * 0.06); g.beginPath(); g.arc(m, m, r * 0.3, 0, Math.PI * 2); g.fillStyle = col; g.fill(); break;
    default: g.beginPath(); g.arc(m, m, r * 0.6, 0, Math.PI * 2); g.fillStyle = col; g.fill();
  }
  ICONS[kind] = c.toDataURL();
  return g.getImageData(0, 0, px, px);
}

// ------------------------------------------------------------------ basemaps (Esri raster tiles; no API key needed)
const ESRI = "https://server.arcgisonline.com/ArcGIS/rest/services/";
const BASES = {
  light: () => [ESRI + `Canvas/${dark() ? "World_Dark_Gray_Base" : "World_Light_Gray_Base"}/MapServer/tile/{z}/{y}/{x}`,
                ESRI + `Canvas/${dark() ? "World_Dark_Gray_Reference" : "World_Light_Gray_Reference"}/MapServer/tile/{z}/{y}/{x}`],
  sat: () => [ESRI + "World_Imagery/MapServer/tile/{z}/{y}/{x}", ESRI + "Reference/World_Boundaries_and_Places/MapServer/tile/{z}/{y}/{x}"],
  topo: () => [ESRI + "World_Topo_Map/MapServer/tile/{z}/{y}/{x}", null],
};
function baseStyle() {
  const sources = {}, layers = [];
  Object.entries(BASES).forEach(([k, f]) => {
    const [base, ref] = f();
    sources["b-" + k] = { type: "raster", tiles: [base], tileSize: 256, maxzoom: k === "light" ? 16 : 19, attribution: "Basemap &copy; Esri and its data providers" };
    layers.push({ id: "b-" + k, type: "raster", source: "b-" + k, layout: { visibility: k === "light" ? "visible" : "none" } });
    if (ref) { sources["r-" + k] = { type: "raster", tiles: [ref], tileSize: 256, maxzoom: 16 }; layers.push({ id: "r-" + k, type: "raster", source: "r-" + k, layout: { visibility: k === "light" ? "visible" : "none" } }); }
  });
  return { version: 8, glyphs: "https://fonts.openmaptiles.org/{fontstack}/{range}.pbf", sources, layers };
}
let base = "light";
function setBase(k) {
  base = k;
  Object.keys(BASES).forEach((b) => ["b-", "r-"].forEach((p) => map.getLayer(p + b) && map.setLayoutProperty(p + b, "visibility", b === k ? "visible" : "none")));
  document.querySelectorAll("#basemaps button").forEach((x) => x.classList.toggle("on", x.dataset.b === k));
  if (map.getLayer("grid-lines")) map.setPaintProperty("grid-lines", "line-color", k === "sat" ? "#ffffff" : css("--ink"));
}

// ------------------------------------------------------------------ map layers
function colorBySymbol() {
  const c = SYM_COLOR();
  return ["match", ["get", "s"], ...SYM.flatMap((s) => [s, c[s]]), c.other];
}
function filterExpr(withOp = true) {
  const parts = ["all"];
  if (hidden.size) parts.push(["!", ["in", ["get", "s"], ["literal", [...hidden]]]]);
  if (withOp && opFilter != null) parts.push(["==", ["get", "o"], opFilter.i]);
  return parts.length > 1 ? parts : null;
}
function applyFilters() {
  ["dots", "wells"].forEach((id) => map.setFilter(id, filterExpr()));
  map.setFilter("laterals", filterExpr(false));
}

function addWellLayers() {
  const url = "pmtiles://" + new URL("data/wells.pmtiles", location.href).href;
  map.addSource("w", { type: "vector", url, attribution: "Wells: AER, Petrinex, BCER, Manitoba Petroleum Branch" });
  SYM.forEach((s) => map.addImage(s, drawIcon(s), { pixelRatio: 2 }));
  map.addLayer({ id: "laterals", type: "line", source: "w", "source-layer": "laterals", minzoom: 9.5,
    paint: { "line-color": colorBySymbol(), "line-width": ["interpolate", ["linear"], ["zoom"], 10, 0.8, 14, 2], "line-opacity": 0.75 } });
  map.addLayer({ id: "dots", type: "circle", source: "w", "source-layer": "dots", maxzoom: 9,
    paint: { "circle-color": colorBySymbol(), "circle-radius": ["interpolate", ["linear"], ["zoom"], 3, 1, 6, 1.8, 9, 3.2],
             "circle-opacity": ["match", ["get", "s"], ["aband", "dry", "other"], 0.35, 0.85] } });
  map.addLayer({ id: "wells", type: "symbol", source: "w", "source-layer": "wells", minzoom: 9,
    layout: { "icon-image": ["get", "s"], "icon-size": ["interpolate", ["linear"], ["zoom"], 9, 0.55, 12, 0.85, 15, 1.15],
              "icon-allow-overlap": true, "icon-ignore-placement": true,
              "symbol-sort-key": ["match", ["get", "s"], ["oil", "gas"], 2, ["oil_susp", "gas_susp", "service"], 1, 0],
              "text-field": ["step", ["zoom"], "", 14.5, ["get", "u"]], "text-font": ["Open Sans Regular"], "text-size": 10.5,
              "text-offset": [0, 1.25], "text-anchor": "top", "text-optional": true },
    paint: { "text-color": css("--ink-2"), "text-halo-color": dark() ? "#000" : "#fff", "text-halo-width": 1.4 } });
  map.addLayer({ id: "sel", type: "circle", source: "w", "source-layer": "wells", minzoom: 9, filter: ["==", ["get", "u"], ""],
    paint: { "circle-radius": 13, "circle-color": "rgba(0,0,0,0)", "circle-stroke-color": css("--accent"), "circle-stroke-width": 3 } });

  map.on("click", "dots", (e) => map.flyTo({ center: e.lngLat, zoom: Math.max(map.getZoom() + 3, 10) }));
  map.on("click", (e) => {
    if (map.getZoom() < 9) return;
    const p = e.point, box = [[p.x - 8, p.y - 8], [p.x + 8, p.y + 8]];
    const fs = map.queryRenderedFeatures(box, { layers: ["wells", "laterals"] });
    const uwis = [...new Map(fs.map((f) => [f.properties.u, f.properties])).values()];
    if (uwis.length === 1) openWell(uwis[0].u);
    else if (uwis.length > 1) showList(uwis, e.lngLat);
  });
  ["wells", "laterals", "dots"].forEach((id) => {
    map.on("mouseenter", id, () => { map.getCanvas().style.cursor = "pointer"; });
    map.on("mouseleave", id, () => { map.getCanvas().style.cursor = ""; });
  });
}

// ------------------------------------------------------------------ DLS grid (township / section / LSD), computed for the view
function sectionCell(sec) { const r = Math.floor((sec - 1) / 6), c = r % 2 === 0 ? (sec - 1) % 6 : 5 - (sec - 1) % 6; return [r, c]; }
function updateGrid() {
  const src = map.getSource("grid"), lab = map.getSource("grid-l"); if (!src || !lab) return;
  const z = map.getZoom(), on = $("#gridT").checked && z >= 7.5;
  const lines = [], labels = [];
  if (on) {
    const b = map.getBounds(), S = Math.max(49, b.getSouth() - 0.1), N = Math.min(60.5, b.getNorth() + 0.1);
    const T = LOC.TWP_KM, fine = z >= 13.5 ? 24 : z >= 11 ? 6 : 1;      // lines per township edge: township, sections, LSDs
    const seg = (p, q, w) => lines.push({ type: "Feature", properties: { w }, geometry: { type: "LineString", coordinates: [p, q] } });
    const label = (pt, l, k) => labels.push({ type: "Feature", properties: { l, k }, geometry: { type: "Point", coordinates: pt } });
    let budget = 3000;                                             // townships drawn at most (keeps panning smooth)
    for (let m = 1; m <= 6 && budget > 0; m++) {
      const east = -LOC.MER[m], westLimit = m < 6 ? -LOC.MER[m + 1] : -122.6;
      if (b.getWest() > east + 0.2 || b.getEast() < westLimit - 0.2 || S >= N) continue;
      const t0 = Math.max(1, Math.floor((S - 49) * 111.2 / T) + 1), t1 = Math.floor((N - 49) * 111.2 / T) + 1;
      const kl = 111.32 * Math.cos(((S + N) / 2) * Math.PI / 180);
      const r0 = Math.max(1, Math.floor((-Math.min(b.getEast(), east) - LOC.MER[m]) * kl / T)), r1 = Math.min(34, Math.ceil((-Math.max(b.getWest(), westLimit) - LOC.MER[m]) * kl / T) + 1);
      for (let t = t0; t <= t1 && budget > 0; t++) for (let r = r0; r <= r1 && budget > 0; r++) {
        const P = (fn, fw) => LOC.townshipPoint(t, r, m, fn, fw);
        const c = P(0.5, 0.5);
        if (c[0] < westLimit || c[0] > east) continue;
        budget--;
        for (let k = 0; k <= fine; k++) {
          const f = k / fine, w = k === 0 || k === fine ? 2 : fine === 24 && k % 4 ? 0 : 1;
          if (k === fine) continue;                                 // the neighbour draws the shared north/west edge
          seg(P(f, 0), P(f, 1), w);                                  // east-west line
          seg(P(0, f), P(1, f), w);                                  // north-south line
        }
        if (z < 11.5) label(c, `${String(t).padStart(3, "0")}-${String(r).padStart(2, "0")}W${m}`, "t");
        else for (let sec = 1; sec <= 36; sec++) {
          if (z < 14.2) label(LOC.dlsToLatLon(null, sec, t, r, m).reverse(), String(sec), "s");
          else for (let lsd = 1; lsd <= 16; lsd++) label(LOC.dlsToLatLon(lsd, sec, t, r, m).reverse(), `${lsd}-${sec}`, "l");
        }
      }
    }
  }
  // lines and labels live in separate sources so a font that fails to load can't take the lines with it
  src.setData({ type: "FeatureCollection", features: lines });
  lab.setData({ type: "FeatureCollection", features: labels });
}
function addGrid() {
  map.addSource("grid", { type: "geojson", data: { type: "FeatureCollection", features: [] } });
  map.addSource("grid-l", { type: "geojson", data: { type: "FeatureCollection", features: [] } });
  map.addLayer({ id: "grid-lines", type: "line", source: "grid",
    paint: { "line-color": css("--ink"), "line-opacity": ["match", ["get", "w"], 2, 0.35, 1, 0.18, 0.09], "line-width": ["match", ["get", "w"], 2, 1.1, 0.7] } }, "laterals");
  map.addLayer({ id: "grid-labels", type: "symbol", source: "grid-l",
    layout: { "text-field": ["get", "l"], "text-font": ["Open Sans Regular"], "text-size": ["match", ["get", "k"], "t", 12, "s", 12, 10], "text-allow-overlap": false },
    paint: { "text-color": css("--muted"), "text-halo-color": dark() ? "#000" : "#fff", "text-halo-width": 1.5 } }, "laterals");
  map.on("moveend", updateGrid);
  updateGrid();
}

// ------------------------------------------------------------------ well panel
const panel = () => $("#panel");
function closePanel() { panel().hidden = true; selected = null; map.setFilter("sel", ["==", ["get", "u"], ""]); setHash(); }
function showList(props, lngLat) {
  const p = panel(); p.hidden = false;
  p.innerHTML = `<div class="ph"><div><h2 style="font-family:var(--font);font-weight:700">${props.length} wells here</h2><div class="name">Pick one</div></div><button class="x" aria-label="Close">×</button></div>
    <div class="list">${props.sort((a, b) => b.b - a.b).map((f) => `<button data-u="${esc(f.u)}"><img src="${ICONS[f.s] || ICONS.other}" alt=""><span><span class="mono">${esc(LOC.display(f.u))}</span>${f.b ? `<br><small class="muted">${n(f.b, 1)} boe/d</small>` : ""}</span></button>`).join("")}</div>`;
  p.querySelector(".x").onclick = closePanel;
  p.querySelectorAll("[data-u]").forEach((b) => b.onclick = () => openWell(b.dataset.u));
}
async function openWell(canon, fly = false) {
  const key = LOC.keyOf(canon), p = panel();
  p.hidden = false; p.innerHTML = `<p class="muted">Loading ${esc(LOC.display(canon))}…</p>`;
  let shard = null, w = null;
  try { shard = await getJSON(`twp/${key}.json`); w = shard.wells[canon]; } catch (e) { /* no shard */ }
  if (!w) {
    p.innerHTML = `<div class="ph"><div><h2>${esc(LOC.display(canon))}</h2><div class="name">Not on the provincial well lists</div></div><button class="x" aria-label="Close">×</button></div>
      <p class="muted" style="margin:0">This UWI isn't in the data. Check the event sequence (the last two digits), or search the legal location to see nearby wells.</p>`;
    p.querySelector(".x").onclick = closePanel; return;
  }
  selected = canon; setHash();
  map.setFilter("sel", ["==", ["get", "u"], canon]);
  if (fly) map.flyTo({ center: [w.x, w.y], zoom: Math.max(map.getZoom(), 14.5), essential: true,
    padding: innerWidth <= 640 ? { bottom: innerHeight * 0.6 } : { left: 420 } });
  const sym = w.s || "other", pr = w.pr, months = shard.months;
  const last3 = (arr) => arr ? arr.slice(-3).reduce((a, b) => a + b, 0) / 3 : 0;
  const cum = (arr, toUnits) => arr ? arr.reduce((a, v, i) => a + v * daysIn(months[i]), 0) / toUnits : 0;
  const latLon = `${n(w.y, 5)}, ${n(w.x, 5)}`;
  const share = location.origin + location.pathname + "#well=" + encodeURIComponent(w.d);
  const prec = { surveyed: "surveyed coordinates", "dls-lsd": "from legal location (±0.5 km)", "dls-section": "section centre (±1 km)", nts: "from NTS location (±0.5 km)" }[w.lp] || "approximate";
  p.innerHTML = `
    <div class="ph"><div><h2>${esc(w.d)}</h2>${w.n ? `<div class="name">${esc(w.n)}</div>` : ""}</div><button class="x" aria-label="Close">×</button></div>
    <div><span class="status"><img src="${ICONS[sym]}" alt="">${esc(META.symbols[sym] || "Other")}</span></div>
    ${pr ? `<div class="rates"><div class="rate"><b>${n(last3(pr[0]), 1)}</b><span>oil bbl/d</span></div><div class="rate"><b>${n(last3(pr[1]), 1)}</b><span>gas mcf/d</span></div><div class="rate"><b>${n(last3(pr[2]), 1)}</b><span>water bbl/d</span></div></div>
      <div class="chart" id="chart"></div>
      <div class="key"><span><i style="background:var(--oil)"></i>Oil bbl/d</span><span><i style="background:var(--gas)"></i>Gas mcf/d (right axis)</span><span><i style="background:var(--svc)"></i>Water bbl/d</span></div>
      <p class="src">Last three months average, per calendar day. ${months.length}-month totals: ${n(cum(pr[0], 1))} bbl oil, ${n(cum(pr[1], 1000), 1)} mmcf gas.</p>` : ""}
    <dl class="facts">
      <div><dt>Licence${w.p === "BC" ? " (WA)" : ""}</dt><dd>${esc(w.li || "–")}</dd></div>
      <div><dt>Licensee</dt><dd>${w.lc ? `<button class="link" data-op="${esc(w.lc)}">${esc(w.lc)}</button>` : "–"}</dd></div>
      <div class="wide"><dt>Status</dt><dd>${esc(w.st || "–")}${w.sd ? ` <span class="muted">· since ${esc(w.sd)}</span>` : ""}</dd></div>
      <div><dt>${w.p === "BC" ? "Rig release" : "Spud date"}</dt><dd>${esc(w.sp || "–")}</dd></div>
      <div><dt>Total depth</dt><dd>${w.td ? n(w.td) + " m" : "–"}</dd></div>
      <div><dt>${w.p === "BC" ? "Area" : "Field"}</dt><dd>${esc(w.fd || "–")}</dd></div>
      <div><dt>${w.p === "AB" ? "Pool code" : "Pool / formation"}</dt><dd>${esc(w.fm || "–")}</dd></div>
      <div><dt>Well type</dt><dd>${w.hz ? "Horizontal" : "Vertical or directional"}</dd></div>
      <div><dt>Province</dt><dd>${esc(PROV[w.p] || w.p)}</dd></div>
      <div class="wide"><dt>Surface location</dt><dd><span class="mono">${latLon}</span> <span class="muted">· ${esc(prec)}</span></dd></div>
      ${w.by ? `<div class="wide"><dt>Bottom hole</dt><dd><span class="mono">${n(w.by, 5)}, ${n(w.bx, 5)}</span></dd></div>` : ""}
    </dl>
    <div class="actions">
      <a class="btn primary" target="_blank" rel="noopener" href="https://www.google.com/maps/dir/?api=1&destination=${w.y},${w.x}">Directions</a>
      <a class="btn" target="_blank" rel="noopener" href="https://maps.apple.com/?daddr=${w.y},${w.x}">Apple Maps</a>
      <button class="btn" id="copyUwi" type="button">Copy UWI</button>
      <button class="btn" id="shareBtn" type="button">Copy link</button>
    </div>
    <p class="src">Source: ${esc(SOURCE[w.p] || "provincial regulator")}. Data through ${esc(META.latest?.[w.p] || META.months?.[1] || "")}.</p>`;
  p.querySelector(".x").onclick = closePanel;
  $("#copyUwi").onclick = () => copy(w.d, "UWI copied");
  $("#shareBtn").onclick = () => copy(share, "Link copied");
  p.querySelectorAll("[data-op]").forEach((b) => b.onclick = () => { const o = OPS.findIndex((x) => x.n === b.dataset.op); if (o >= 0) setOperator(o); });
  if (pr) productionChart($("#chart"), months, pr);
  p.scrollTop = 0;
}
function daysIn(m) { const [y, mm] = m.split("-").map(Number); return new Date(y, mm, 0).getDate(); }
function productionChart(host, months, pr) {
  const W = 360, H = 150, L = 34, R = 36, T = 8, B = 20, k = months.length;
  const oil = pr[0] || months.map(() => 0), gas = pr[1] || months.map(() => 0), wat = pr[2] || months.map(() => 0);
  const nice = (v) => { if (!(v > 0)) return 1; const p = 10 ** Math.floor(Math.log10(v)), q = v / p; return (q <= 1 ? 1 : q <= 2 ? 2 : q <= 5 ? 5 : 10) * p; };
  const yl = nice(Math.max(...oil, ...wat, 0.1)), yr = nice(Math.max(...gas, 0.1));
  const x = (i) => L + i / Math.max(k - 1, 1) * (W - L - R), y1 = (v) => T + (H - T - B) * (1 - v / yl), y2 = (v) => T + (H - T - B) * (1 - v / yr);
  const line = (a, y, c, dash = "") => `<path d="M${a.map((v, i) => `${x(i).toFixed(1)},${y(v).toFixed(1)}`).join(" L")}" fill="none" stroke="${c}" stroke-width="1.8" ${dash ? `stroke-dasharray="${dash}"` : ""}/>`;
  let ticks = "";
  months.forEach((m, i) => { if (m.endsWith("-01")) ticks += `<text x="${x(i)}" y="${H - 5}" text-anchor="middle">${m.slice(0, 4)}</text>`; });
  host.innerHTML = `<svg viewBox="0 0 ${W} ${H}" role="img" aria-label="Monthly production">
    ${[0, 0.5, 1].map((f) => `<line class="g" x1="${L}" x2="${W - R}" y1="${T + (H - T - B) * (1 - f)}" y2="${T + (H - T - B) * (1 - f)}"/>
      <text x="${L - 5}" y="${T + (H - T - B) * (1 - f) + 3}" text-anchor="end">${n(yl * f)}</text><text x="${W - R + 5}" y="${T + (H - T - B) * (1 - f) + 3}">${n(yr * f)}</text>`).join("")}
    ${line(wat, y1, css("--svc"), "3 3")}${line(gas, y2, css("--gas"))}${line(oil, y1, css("--oil"))}${ticks}
    <g class="hover" style="display:none"><line class="guide" y1="${T}" y2="${H - B}" stroke="${css("--ink")}" stroke-dasharray="2 3"/>
      <circle class="d-oil" r="3" fill="${css("--oil")}"/><circle class="d-gas" r="3" fill="${css("--gas")}"/><circle class="d-wat" r="3" fill="${css("--svc")}"/></g>
    <rect x="${L}" y="${T}" width="${W - L - R}" height="${H - T - B}" fill="transparent" class="hit"/></svg>
    <div class="ctip" hidden></div>`;
  // Hover (or touch-drag) to read the month's rates
  const svg = host.querySelector("svg"), hov = svg.querySelector(".hover"), tip = host.querySelector(".ctip");
  const label = (m) => { const [yy, mm] = m.split("-").map(Number); return new Date(yy, mm - 1, 1).toLocaleString("en-CA", { month: "short", year: "numeric" }); };
  const show = (clientX) => {
    const r = svg.getBoundingClientRect(), px = (clientX - r.left) / r.width * W;
    const i = Math.max(0, Math.min(k - 1, Math.round((px - L) / (W - L - R) * (k - 1))));
    hov.style.display = "";
    hov.querySelector(".guide").setAttribute("x1", x(i)); hov.querySelector(".guide").setAttribute("x2", x(i));
    [["d-oil", oil, y1], ["d-gas", gas, y2], ["d-wat", wat, y1]].forEach(([c, a, y]) => { const d = hov.querySelector("." + c); d.setAttribute("cx", x(i)); d.setAttribute("cy", y(a[i])); });
    tip.hidden = false;
    tip.innerHTML = `<b>${label(months[i])}</b><span><i style="background:var(--oil)"></i>${n(oil[i], 1)} bbl/d oil</span><span><i style="background:var(--gas)"></i>${n(gas[i], 1)} mcf/d gas</span><span><i style="background:var(--svc)"></i>${n(wat[i], 1)} bbl/d water</span>`;
    const left = (x(i) / W) * r.width;
    tip.style.left = Math.max(0, Math.min(r.width - tip.offsetWidth, left - tip.offsetWidth / 2)) + "px";
  };
  const hide = () => { hov.style.display = "none"; tip.hidden = true; };
  svg.addEventListener("pointermove", (e) => show(e.clientX));
  svg.addEventListener("pointerdown", (e) => show(e.clientX));
  svg.addEventListener("pointerleave", hide);
}
function copy(text, msg) {
  const done = () => toast(msg);
  if (navigator.clipboard) navigator.clipboard.writeText(text).then(done).catch(() => prompt("Copy:", text)); else prompt("Copy:", text);
}
let toastT;
function toast(msg) { const t = $("#toast"); t.textContent = msg; t.hidden = false; clearTimeout(toastT); toastT = setTimeout(() => (t.hidden = true), 1800); }

// ------------------------------------------------------------------ operators
function setOperator(i) {
  if (i != null && selected) { panel().hidden = true; selected = null; map.setFilter("sel", ["==", ["get", "u"], ""]); }
  opFilter = i == null ? null : { i, ...OPS[i] };
  applyFilters();
  const chip = $("#opFilter");
  if (!opFilter) { chip.hidden = true; setHash(); return; }
  chip.hidden = false;
  chip.innerHTML = `<span>${esc(opFilter.n)} · ${n(opFilter.w)} wells</span><button aria-label="Show all operators">×</button>`;
  chip.querySelector("button").onclick = () => setOperator(null);
  const [w, s, e, nn] = opFilter.b;
  map.fitBounds([[w, s], [e, nn]], { padding: 60, maxZoom: 12 });
  setHash();
}

// ------------------------------------------------------------------ search
let sugg = [], active = 0;
async function suggestions(text) {
  const out = [], t = text.trim();
  if (!t) return out;
  const p = LOC.parse(t);
  if (p) out.push(p.kind === "uwi" ? { label: `Well ${p.label}`, hint: "UWI", go: () => openWell(p.canon, true) }
                                  : { label: p.label, hint: "Legal location", go: () => { map.flyTo({ center: [p.lon, p.lat], zoom: p.zoom }); closeSuggest(); } });
  if (/^[0-9A-Z]{3,10}$/i.test(t)) {
    const li = t.toUpperCase().replace(/^0+/, ""), shard = li.slice(-2).padStart(2, "0");
    try {
      const idx = await getJSON(`lic/${shard}.json`);
      (idx[li] || []).slice(0, 6).forEach(([prov, u]) => out.push({ label: `Licence ${li} · ${LOC.display(u)}`, hint: prov, go: () => openWell(u, true) }));
    } catch (e) { /* no licence shard */ }
  }
  if (t.length >= 2 && !p) {
    const q = t.toLowerCase();
    OPS.map((o, i) => [o, i]).filter(([o]) => o.n.toLowerCase().includes(q)).slice(0, 7)
      .forEach(([o, i]) => out.push({ label: o.n, hint: `${n(o.w)} wells`, go: () => setOperator(i) }));
  }
  return out;
}
function renderSuggest() {
  const box = $("#suggest");
  if (!sugg.length) { box.hidden = true; return; }
  box.hidden = false;
  box.innerHTML = sugg.map((s, i) => `<button class="${i === active ? "on" : ""}" data-i="${i}"><span>${esc(s.label)}</span><small>${esc(s.hint)}</small></button>`).join("");
  box.querySelectorAll("button").forEach((b) => b.onmousedown = (e) => { e.preventDefault(); pick(+b.dataset.i); });
}
function pick(i) { const s = sugg[i]; if (!s) return; closeSuggest(); $("#q").blur(); s.go(); }
function closeSuggest() { $("#suggest").hidden = true; }
function initSearch() {
  const q = $("#q");
  let seq = 0;
  q.addEventListener("input", async () => {
    const my = ++seq; const s = await suggestions(q.value);
    if (my !== seq) return;
    sugg = s; active = 0; renderSuggest();
    if (q.value.trim() && !s.length) { $("#suggest").hidden = false; $("#suggest").innerHTML = `<button disabled><span class="muted">No match. Try a UWI like 100/06-06-001-01W4/00, a licence number, a location like 06-06-001-01W4, or an operator.</span></button>`; }
  });
  q.addEventListener("keydown", (e) => {
    if (e.key === "ArrowDown") { active = Math.min(active + 1, sugg.length - 1); renderSuggest(); e.preventDefault(); }
    else if (e.key === "ArrowUp") { active = Math.max(active - 1, 0); renderSuggest(); e.preventDefault(); }
    else if (e.key === "Enter") { pick(active); }
    else if (e.key === "Escape") { closeSuggest(); q.blur(); }
  });
  q.addEventListener("blur", () => setTimeout(closeSuggest, 150));
}

// ------------------------------------------------------------------ layers panel, legend, about
function initLayers() {
  const btn = $("#layersBtn"), box = $("#layers");
  btn.onclick = () => { box.hidden = !box.hidden; btn.setAttribute("aria-expanded", String(!box.hidden)); };
  document.querySelectorAll("#basemaps button").forEach((b) => b.onclick = () => setBase(b.dataset.b));
  $("#gridT").onchange = updateGrid;
  $("#latT").onchange = (e) => map.setLayoutProperty("laterals", "visibility", e.target.checked ? "visible" : "none");
  const counts = META.counts.by_symbol || {};
  $("#wellCount").textContent = n(META.counts.wells) + " total";
  $("#legend").innerHTML = SYM.filter((s) => counts[s]).map((s) => `<label><input type="checkbox" data-s="${s}" checked><img src="${ICONS[s]}" alt=""><span>${esc(META.symbols[s])}</span><small>${n(counts[s])}</small></label>`).join("");
  $("#legend").querySelectorAll("input").forEach((c) => c.onchange = () => { c.checked ? hidden.delete(c.dataset.s) : hidden.add(c.dataset.s); applyFilters(); });
  $("#aboutBtn").onclick = about;
}
function about() {
  const m = META, c = m.counts, modal = $("#about");
  modal.hidden = false;
  modal.querySelector(".sheet").innerHTML = `<div class="ph"><h2 id="aboutTitle" style="font-family:var(--font)">About WellScope</h2><button class="x" aria-label="Close">×</button></div>
    <p>A free map of every oil and gas well in Alberta, Saskatchewan, British Columbia and Manitoba, rebuilt every month from the regulators' public files. No account needed.</p>
    <ul>${Object.entries(c.by_province || {}).map(([p, v]) => `<li><b>${PROV[p]}</b>: ${n(v)} wells. ${esc(SOURCE[p])}. Data through ${esc(m.latest?.[p] || "")}.</li>`).join("")}</ul>
    <p>${n(c.producing)} wells reported production in the last three months. ${n(c.laterals)} horizontal laterals are drawn from published bottom-hole coordinates (Alberta).</p>
    <p class="muted">Search accepts a UWI in any common format, a licence or well authorization number, a legal location (06-06-001-01W4, 060-12W5) or an operator. Wells without published coordinates are placed from their legal location, so they can be a few hundred metres off. Production is gross, per calendar day. Check each regulator's terms before reusing the data commercially.</p>
    <p class="muted">Generated ${esc(m.generated)} · <a href="https://github.com/kosherite/wellscope" target="_blank" rel="noopener">Source code</a></p>`;
  const close = () => (modal.hidden = true);
  modal.querySelector(".x").onclick = close;
  modal.onclick = (e) => { if (e.target === modal) close(); };
}

// ------------------------------------------------------------------ URL state: #well=…, #op=…, #@lat,lon,zoom
let hashLock = false;
function setHash() {
  if (hashLock) return;
  let h;
  if (selected) h = "#well=" + encodeURIComponent(LOC.display(selected));
  else if (opFilter) h = "#op=" + encodeURIComponent(opFilter.n);
  else { const c = map.getCenter(); h = `#@${c.lat.toFixed(4)},${c.lng.toFixed(4)},${map.getZoom().toFixed(1)}`; }
  history.replaceState(null, "", h);
}
function readHash() {
  const h = decodeURIComponent(location.hash.slice(1));
  hashLock = true;
  try {
    if (h.startsWith("well=")) { const p = LOC.parse(h.slice(5)); if (p && p.kind === "uwi") { map.jumpTo({ center: [p.lon, p.lat], zoom: 14.5 }); openWell(p.canon, true); } }
    else if (h.startsWith("op=")) { const i = OPS.findIndex((o) => o.n === h.slice(3)); if (i >= 0) setOperator(i); }
    else if (h.startsWith("@")) { const [la, lo, z] = h.slice(1).split(",").map(Number); if (isFinite(la)) map.jumpTo({ center: [lo, la], zoom: z || 10 }); }
  } finally { hashLock = false; }
}

// ------------------------------------------------------------------ start
(async function start() {
  try { [META, OPS] = await Promise.all([getJSON("meta.json"), getJSON("operators.json")]); LOC.setOffsets(await getJSON("grid_offsets.json").catch(() => ({}))); }
  catch (e) { document.body.insertAdjacentHTML("beforeend", `<div class="modal"><div class="sheet"><h2>No map data yet</h2><p>Run the pipeline (<span class="mono">python -m wellscope run</span>, or the "Build basin data" action) to create <span class="mono">site/data</span>.</p></div></div>`); return; }
  if (typeof maplibregl === "undefined" || typeof pmtiles === "undefined") { toast("The map library couldn't load. Check your connection and reload."); return; }
  const protocol = new pmtiles.Protocol();
  maplibregl.addProtocol("pmtiles", protocol.tile);
  map = new maplibregl.Map({ container: "map", style: baseStyle(), center: [-113.5, 54.2], zoom: 4.6, maxZoom: 18, minZoom: 3, hash: false, attributionControl: { compact: true } });
  map.addControl(new maplibregl.NavigationControl({ visualizePitch: false }), "bottom-right");
  map.addControl(new maplibregl.GeolocateControl({ positionOptions: { enableHighAccuracy: true }, trackUserLocation: true }), "bottom-right");
  map.addControl(new maplibregl.ScaleControl({ unit: "metric" }), "bottom-left");
  map.on("load", () => {
    addWellLayers(); addGrid(); initLayers(); initSearch();
    readHash();
    map.on("moveend", () => { if (!selected && !opFilter) setHash(); });
  });
  addEventListener("keydown", (e) => { if (e.key === "Escape") { closePanel(); $("#about").hidden = true; } });
})();
