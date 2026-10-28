/* WellScope front end. Plain JS, no build step. Data comes from ./data/*.json written by the Python pipeline. */
"use strict";

const $ = (s, el = document) => el.querySelector(s);
const esc = (s) => String(s ?? "").replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
const PROV = { AB: "Alberta", SK: "Saskatchewan", BC: "British Columbia", MB: "Manitoba" };
const PCOL = { AB: "--sky-ink", SK: "--butter-ink", BC: "--mint-ink", MB: "--lilac-ink" };
const css = (v) => getComputedStyle(document.documentElement).getPropertyValue(v).trim();

const fmt = {
  n(v, d = 0) { if (v == null || !isFinite(v)) return "–"; return Number(v).toLocaleString("en-CA", { maximumFractionDigits: d, minimumFractionDigits: d }); },
  k(v) { if (v == null || !isFinite(v)) return "–"; const a = Math.abs(v); return a >= 1e6 ? (v / 1e6).toFixed(a >= 1e7 ? 1 : 2) + "M" : a >= 1e4 ? (v / 1e3).toFixed(1) + "k" : fmt.n(v); },
  money(v) { if (v == null || !isFinite(v)) return "–"; const a = Math.abs(v); return (v < 0 ? "−" : "") + "$" + (a >= 1e9 ? (a / 1e9).toFixed(2) + "B" : a >= 1e6 ? (a / 1e6).toFixed(1) + "M" : a >= 1e3 ? (a / 1e3).toFixed(0) + "k" : a.toFixed(0)); },
  decl(v) { if (v == null || !isFinite(v)) return "–"; return v < 0 ? "+" + fmt.n(-v, 1) + "% growth" : fmt.n(v, 1) + "%"; },
  pv(pv) { if (!pv) return "–"; if (pv.nb <= 0) return "Uneconomic"; return fmt.money((pv.lo + pv.hi) / 2); },
  pct(v, d = 0) { return v == null || !isFinite(v) ? "–" : fmt.n(v, d) + "%"; },
  month(m) { if (!m) return "–"; const [y, mm] = m.split("-"); return new Date(+y, +mm - 1, 1).toLocaleString("en-CA", { month: "short", year: "numeric" }); },
};

// ------------------------------------------------------------------ data
const cache = new Map();
async function getJSON(path) {
  if (!cache.has(path)) cache.set(path, fetch("data/" + path).then((r) => { if (!r.ok) throw new Error(path + " " + r.status); return r.json(); }));
  return cache.get(path);
}
let META, BASIN, CELLS, OPS;

// ------------------------------------------------------------------ price deck
const DECK_FIELDS = [
  ["wti_usd", "WTI (US$/bbl)", 1], ["oil_diff_usd", "Light oil differential to WTI (US$/bbl)", 0.5], ["fx_usdcad", "US$ per C$", 0.01],
  ["aeco_cad_gj", "AECO gas (C$/GJ)", 0.05], ["royalty", "Royalty rate (0 to 1)", 0.01], ["opex_cad_boe", "Operating cost (C$/boe)", 0.5],
  ["transport_cad_boe", "Transportation (C$/boe)", 0.25], ["discount", "Discount rate (0.10 = PV10)", 0.01],
];
let DECK = {};
function loadDeck() {
  DECK = { ...META.price_deck };
  try { Object.assign(DECK, JSON.parse(localStorage.getItem("wellscope.deck") || "{}")); } catch (e) { /* storage unavailable */ }
}
function saveDeck() { try { localStorage.setItem("wellscope.deck", JSON.stringify(DECK)); } catch (e) { /* ignore */ } }
const oilPrice = () => (DECK.wti_usd - DECK.oil_diff_usd) / DECK.fx_usdcad;                // C$/bbl
const gasPerBoe = () => DECK.aeco_cad_gj * 1.055 * 6;                                        // C$ per boe of gas
function netback(oilFrac) {
  const rev = oilFrac * oilPrice() + (1 - oilFrac) * gasPerBoe();
  return rev * (1 - DECK.royalty) - DECK.opex_cad_boe - DECK.transport_cad_boe;
}
function arps(t, qi, di, b) { return qi / Math.pow(1 + b * di * t, 1 / b); }
function forecast(fit, months) {           // fit = [b, di, q_now, t_now]
  const [b, di, q, tn] = fit, qi = q * Math.pow(1 + b * di * tn, 1 / b), out = [];
  let qt = null, m0 = 0;
  for (let m = 1; m <= months; m++) {
    const t = tn + m / 12;
    if (qt == null && di / (1 + b * di * t) <= 0.06) { qt = arps(t, qi, di, b); m0 = m; }
    out.push(qt != null ? qt * Math.exp(-0.06 * (m - m0) / 12) : arps(t, qi, di, b));
  }
  return out;
}
function pvRange(pdp) {
  if (!pdp) return null;
  const nb = netback(pdp.oil_frac ?? 0.5);
  const vals = pdp.fits.map((f) => {
    const q = forecast(f, 360); let pv = 0, vol = 0;
    q.forEach((r, i) => { const v = r * 30.4; vol += v; if (nb > 0) pv += v * nb / Math.pow(1 + DECK.discount, (i + 1) / 12); });
    return { pv, vol };
  });
  return { lo: Math.min(...vals.map((v) => v.pv)), hi: Math.max(...vals.map((v) => v.pv)), nb,
           eur: [Math.min(...vals.map((v) => v.vol)), Math.max(...vals.map((v) => v.vol))] };
}
function renderDeck() {
  $("#deckFields").innerHTML = DECK_FIELDS.map(([k, label, step]) =>
    `<div class="field"><label for="deck-${k}">${label}</label><input id="deck-${k}" type="number" inputmode="decimal" step="${step}" value="${DECK[k]}"></div>`).join("");
  DECK_FIELDS.forEach(([k]) => $("#deck-" + k).addEventListener("input", (e) => {
    const v = parseFloat(e.target.value); if (!isFinite(v)) return;
    DECK[k] = v; saveDeck(); deckSummary(); route();
  }));
  deckSummary();
}
function deckSummary() {
  $("#deckSummary").textContent = `WTI $${fmt.n(DECK.wti_usd)} · AECO $${fmt.n(DECK.aeco_cad_gj, 2)}`;
  $("#nbOil").textContent = "C$" + fmt.n(netback(1), 2) + "/bbl";
  $("#nbGas").textContent = "C$" + fmt.n(netback(0), 2) + "/boe";
}

// ------------------------------------------------------------------ charts (inline SVG)
const tip = document.createElement("div"); tip.className = "tip"; tip.hidden = true; document.body.appendChild(tip);
function svgEl(w, h) { return `<svg viewBox="0 0 ${w} ${h}" role="img">`; }
function niceMax(v) { if (!(v > 0)) return 1; const p = Math.pow(10, Math.floor(Math.log10(v))); const n = v / p; return (n <= 1 ? 1 : n <= 2 ? 2 : n <= 2.5 ? 2.5 : n <= 5 ? 5 : 10) * p; }
function axes(W, H, L, R, T, B, ymax, ticks = 4, unit = "") {
  let s = "";
  for (let i = 0; i <= ticks; i++) {
    const v = ymax * i / ticks, y = T + (H - T - B) * (1 - i / ticks);
    s += `<line class="grid" x1="${L}" x2="${W - R}" y1="${y}" y2="${y}"/><text x="${L - 8}" y="${y + 4}" text-anchor="end">${fmt.k(v)}${i === ticks ? unit : ""}</text>`;
  }
  return s;
}
function monthTicks(months, x, H, B) {
  let s = "";
  months.forEach((m, i) => { if (m.endsWith("-01") || (months.length < 14 && i % 3 === 0)) s += `<text x="${x(i)}" y="${H - B + 18}" text-anchor="middle">${m.endsWith("-01") ? m.slice(0, 4) : fmt.month(m)}</text>`; });
  return s;
}
function attachHover(host, n, x, label) {
  const svg = host.querySelector("svg"), guide = host.querySelector(".guide");
  if (!svg) return;
  svg.addEventListener("pointermove", (e) => {
    const r = svg.getBoundingClientRect(), vb = svg.viewBox.baseVal, px = (e.clientX - r.left) / r.width * vb.width;
    let best = 0, bd = 1e9;
    for (let i = 0; i < n; i++) { const d = Math.abs(x(i) - px); if (d < bd) { bd = d; best = i; } }
    if (guide) { guide.setAttribute("x1", x(best)); guide.setAttribute("x2", x(best)); guide.style.opacity = 1; }
    tip.innerHTML = label(best); tip.hidden = false;
    tip.style.left = Math.min(innerWidth - 270, e.clientX + 14) + "px"; tip.style.top = (e.clientY + 14) + "px";
  });
  svg.addEventListener("pointerleave", () => { tip.hidden = true; if (guide) guide.style.opacity = 0; });
}

/** Stacked oil + gas (as boe) production history. */
function historyChart(host, months, oil, gas) {
  const W = 760, H = 280, L = 52, R = 12, T = 12, B = 30, n = months.length;
  const gasBoe = gas.map((g) => g / 6), tot = oil.map((o, i) => o + gasBoe[i]);
  const ymax = niceMax(Math.max(...tot, 1)), x = (i) => L + (n === 1 ? 0 : i / (n - 1)) * (W - L - R), y = (v) => T + (H - T - B) * (1 - v / ymax);
  const area = (top, bot) => "M" + top.map((v, i) => `${x(i)},${y(v)}`).join(" L") + " L" + bot.map((v, i) => `${x(n - 1 - i)},${y(bot[n - 1 - i])}`).join(" L") + "Z";
  const zero = months.map(() => 0);
  host.innerHTML = `<div class="chart">${svgEl(W, H)}${axes(W, H, L, R, T, B, ymax)}
    <path d="${area(oil, zero)}" fill="${css("--oil")}" fill-opacity=".85"/>
    <path d="${area(tot, oil)}" fill="${css("--gas")}" fill-opacity=".55"/>
    <path d="M${tot.map((v, i) => `${x(i)},${y(v)}`).join(" L")}" fill="none" stroke="${css("--ink")}" stroke-width="1.6"/>
    ${monthTicks(months, x, H, B)}<line class="guide" x1="0" x2="0" y1="${T}" y2="${H - B}" stroke="${css("--ink")}" stroke-dasharray="3 3" style="opacity:0"/></svg>
    <div class="legend"><span><i style="background:var(--oil)"></i>Oil + condensate (bbl/d)</span><span><i style="background:var(--gas);opacity:.6"></i>Gas (boe/d at 6:1)</span><span><i style="background:var(--ink)"></i>Total boe/d</span></div></div>`;
  attachHover(host, n, x, (i) => `<b>${fmt.month(months[i])}</b><br>${fmt.n(tot[i])} boe/d<br>Oil ${fmt.n(oil[i])} bbl/d · Gas ${fmt.n(gas[i])} mcf/d`);
}

/** History plus a forecast band across decline shapes (the PDP view). */
function forecastChart(host, months, hist, pdp, ahead = 60) {
  if (pdp && pdp.hist) { hist = pdp.hist; months = months.slice(-hist.length); }
  if (!pdp) { host.innerHTML = `<div class="empty">Not enough steady history to fit a decline here yet.</div>`; return; }
  const W = 760, H = 280, L = 52, R = 12, T = 12, B = 30, h = hist.length, n = h + ahead;
  const fc = pdp.fits.map((f) => forecast(f, ahead));
  const lo = fc[0].map((_, i) => Math.min(...fc.map((s) => s[i]))), hi = fc[0].map((_, i) => Math.max(...fc.map((s) => s[i])));
  const ymax = niceMax(Math.max(...hist, ...hi, 1)), x = (i) => L + i / (n - 1) * (W - L - R), y = (v) => T + (H - T - B) * (1 - v / ymax);
  const allMonths = months.slice(); const [yy, mm] = months[h - 1].split("-").map(Number);
  for (let k = 1; k <= ahead; k++) { const d = new Date(yy, mm - 1 + k, 1); allMonths.push(d.getFullYear() + "-" + String(d.getMonth() + 1).padStart(2, "0")); }
  const band = "M" + hi.map((v, i) => `${x(h + i)},${y(v)}`).join(" L") + " L" + lo.slice().reverse().map((v, i) => `${x(h + ahead - 1 - i)},${y(v)}`).join(" L") + ` L${x(h - 1)},${y(hist[h - 1])} Z`;
  host.innerHTML = `<div class="chart">${svgEl(W, H)}${axes(W, H, L, R, T, B, ymax, 4, "")}
    <rect x="${x(h - 1)}" y="${T}" width="${W - R - x(h - 1)}" height="${H - T - B}" fill="${css("--soft")}" opacity=".6"/>
    <path d="${band}" fill="${css("--band")}" stroke="${css("--lilac-ink")}" stroke-width=".8" stroke-dasharray="3 3"/>
    <path d="M${hist.map((v, i) => `${x(i)},${y(v)}`).join(" L")}" fill="none" stroke="${css("--ink")}" stroke-width="2"/>
    <circle cx="${x(h - 1)}" cy="${y(hist[h - 1])}" r="4" fill="${css("--ink")}"/>
    <text x="${x(h - 1) + 8}" y="${T + 14}">forecast →</text><text x="${x(h - 1) - 8}" y="${T + 14}" text-anchor="end">← reported</text>
    ${monthTicks(allMonths, x, H, B)}<line class="guide" x1="0" x2="0" y1="${T}" y2="${H - B}" stroke="${css("--ink")}" stroke-dasharray="3 3" style="opacity:0"/></svg>
    <div class="legend"><span><i style="background:var(--ink)"></i>Reported boe/d, wells online 12+ months</span><span><i style="background:var(--band);border:1px dashed var(--lilac-ink)"></i>Forecast range, decline shape b = 0.3 to 1.0</span></div></div>`;
  attachHover(host, n, x, (i) => i < h ? `<b>${fmt.month(allMonths[i])}</b><br>${fmt.n(hist[i])} boe/d reported` :
    `<b>${fmt.month(allMonths[i])}</b><br>${fmt.n(lo[i - h])} to ${fmt.n(hi[i - h])} boe/d forecast`);
}

/** Type curve: P10–P90 band and P50 by month on production. */
function typeCurveChart(host, tc, color = "--lilac-ink", tc2 = null) {
  if (!tc) { host.innerHTML = `<div class="empty">Type curves need at least five new wells with individual production. They appear once well-level data is loaded for this area.</div>`; return; }
  const W = 760, H = 260, L = 52, R = 12, T = 12, B = 34, n = tc.p50.length;
  const ymax = niceMax(Math.max(...tc.p10, ...(tc2 ? tc2.p10 : []), 1)), x = (i) => L + (n === 1 ? 0 : i / Math.max(n - 1, 1)) * (W - L - R), y = (v) => T + (H - T - B) * (1 - v / ymax);
  const band = (c) => "M" + c.p10.map((v, i) => `${x(i)},${y(v)}`).join(" L") + " L" + c.p90.slice().reverse().map((v, i) => `${x(c.p90.length - 1 - i)},${y(v)}`).join(" L") + "Z";
  const line = (a) => "M" + a.map((v, i) => `${x(i)},${y(v)}`).join(" L");
  let ticks = ""; for (let i = 0; i < n; i += Math.max(1, Math.round(n / 8))) ticks += `<text x="${x(i)}" y="${H - B + 18}" text-anchor="middle">${i + 1}</text>`;
  host.innerHTML = `<div class="chart">${svgEl(W, H)}${axes(W, H, L, R, T, B, ymax)}
    <path d="${band(tc)}" fill="${css(color)}" fill-opacity=".16"/>
    <path d="${line(tc.p50)}" fill="none" stroke="${css(color)}" stroke-width="2.4"/>
    ${tc2 ? `<path d="${band(tc2)}" fill="${css("--peach-ink")}" fill-opacity=".12"/><path d="${line(tc2.p50)}" fill="none" stroke="${css("--peach-ink")}" stroke-width="2" stroke-dasharray="5 4"/>` : ""}
    ${ticks}<text x="${W - R}" y="${H - 4}" text-anchor="end">months on production</text>
    <line class="guide" x1="0" x2="0" y1="${T}" y2="${H - B}" stroke="${css("--ink")}" stroke-dasharray="3 3" style="opacity:0"/></svg>
    <div class="legend"><span><i style="background:${css(color)}"></i>${tc2 ? "Horizontal wells, " : ""}P50 with P10–P90 band</span>${tc2 ? `<span><i style="background:var(--peach-ink)"></i>Vertical wells, P50</span>` : ""}<span>${fmt.n(tc.n[0])} wells in month 1</span></div></div>`;
  attachHover(host, n, x, (i) => `<b>Month ${i + 1}</b> · ${tc.n[i]} wells<br>P10 ${fmt.n(tc.p10[i])} · P50 ${fmt.n(tc.p50[i])} · P90 ${fmt.n(tc.p90[i])} boe/d`);
}

function barsChart(host, labels, series) {   // series: [{name, color, values}]
  const W = 760, H = 240, L = 44, R = 8, T = 10, B = 28, n = labels.length;
  const tot = labels.map((_, i) => series.reduce((a, s) => a + (s.values[i] || 0), 0));
  const ymax = niceMax(Math.max(...tot, 1)), bw = (W - L - R) / n * 0.7, x = (i) => L + (i + 0.15) * (W - L - R) / n, y = (v) => T + (H - T - B) * (1 - v / ymax);
  let s = "";
  labels.forEach((lab, i) => {
    let acc = 0;
    series.forEach((se) => { const v = se.values[i] || 0; if (v) s += `<rect x="${x(i)}" y="${y(acc + v)}" width="${bw}" height="${y(acc) - y(acc + v)}" rx="3" fill="${css(se.color)}"/>`; acc += v; });
    s += `<text x="${x(i) + bw / 2}" y="${H - B + 16}" text-anchor="middle">${lab}</text>`;
  });
  host.innerHTML = `<div class="chart">${svgEl(W, H)}${axes(W, H, L, R, T, B, ymax)}${s}</svg><div class="legend">${series.map((se) => `<span><i style="background:var(${se.color})"></i>${esc(se.name)}</span>`).join("")}</div></div>`;
}

function spark(v, w = 96, h = 26) {
  if (!v || !v.length) return "";
  const mx = Math.max(...v, 1e-9), x = (i) => i / Math.max(v.length - 1, 1) * w, y = (q) => h - 2 - (q / mx) * (h - 4);
  return `<svg width="${w}" height="${h}" viewBox="0 0 ${w} ${h}" aria-hidden="true"><path d="M${v.map((q, i) => `${x(i)},${y(q)}`).join(" L")}" fill="none" stroke="${css("--lilac-ink")}" stroke-width="1.6"/></svg>`;
}

// ------------------------------------------------------------------ shared blocks
function tile(color, k, v, s = "") { return `<div class="tile t-${color}"><span class="k">${k}</span><span class="v">${v}</span>${s ? `<span class="s">${s}</span>` : ""}</div>`; }
function metricTiles(m, extra = "") {
  const pv = pvRange(m.pdp);
  return `<div class="tiles">
    ${tile("lilac", "Production", fmt.k(m.boe) + " <small style='font-size:15px'>boe/d</small>", `${fmt.k(m.oil)} bbl/d oil · ${fmt.k(m.gas)} mcf/d gas`)}
    ${tile("mint", "Oil weighting", fmt.pct(m.oil_pct), `Water cut ${fmt.pct(m.wcut)} · GOR ${m.gor ? fmt.k(m.gor) + " scf/bbl" : "–"}`)}
    ${tile("peach", "Base decline", fmt.decl(m.decline), "Wells online 15+ months, year over year")}
    ${tile("sky", "PDP value (PV)", pv ? (pv.nb <= 0 ? "Uneconomic" : `${fmt.money(pv.lo)}–${fmt.money(pv.hi).replace("$", "")}`) : "–", pv ? `At your deck, netback C$${fmt.n(pv.nb, 2)}/boe` : "Needs a decline fit")}
    ${tile("butter", "New wells, 12 months", fmt.n(m.new12), m.ip90 ? `Median IP90 ${fmt.n(m.ip90)} boe/d` : "First production in the last year")}
    ${extra}</div>`;
}
function wellsTable(list) {
  if (!list || !list.length) return `<div class="empty">No producing wells or facilities listed here.</div>`;
  return `<div class="tablewrap"><table><thead><tr><th>Well or facility</th><th>Operator</th><th>Status</th><th class="n">boe/d</th><th class="n">Oil bbl/d</th><th>Last 24 months</th><th>First prod.</th></tr></thead><tbody>
    ${list.map((w) => `<tr data-lat="${w.lat ?? ""}" data-lon="${w.lon ?? ""}"><td><span class="mono">${esc(w.id)}</span>${w.name ? `<div class="muted" style="font-size:12.5px">${esc(w.name)}</div>` : w.type === "facility" ? `<div class="muted" style="font-size:12.5px">Facility (several wells)</div>` : ""}</td>
      <td>${esc(w.op)}</td><td>${w.status ? `<span class="tag ${esc(w.status)}">${esc(w.status)}</span>` : ""}${w.hz ? ` <span class="tag Other">HZ</span>` : ""}</td>
      <td class="n">${fmt.n(w.boe, 1)}</td><td class="n">${fmt.n(w.oil, 1)}</td><td>${spark(w.spark)}</td><td>${w.first && w.first === META.months[0] ? "Before " + fmt.month(w.first) : fmt.month(w.first)}</td></tr>`).join("")}
    </tbody></table></div>`;
}
function snapshotBanner() {
  const provs = Object.keys(META.latest);
  if (META.counts.well_level_share > 0.2 && provs.length > 1) return "";
  return `<div class="banner"><span>⚑</span><div><b>Pilot snapshot.</b> This copy shows real Petrinex data for ${provs.map((p) => PROV[p]).join(", ")} around Whitecourt, at battery level. The scheduled pipeline replaces it with every well in Alberta, Saskatchewan, BC and Manitoba.</div></div>`;
}

// ------------------------------------------------------------------ views
function setNav(r) { document.querySelectorAll("#nav a").forEach((a) => a.classList.toggle("on", r.startsWith(a.dataset.r))); }

function overview() {
  const b = BASIN.basin, provs = Object.entries(BASIN.provinces);
  const v = $("#view");
  v.innerHTML = `${snapshotBanner()}
  <section style="display:grid;gap:14px">
    <span class="eyebrow">Western Canadian Sedimentary Basin · data through ${fmt.month(META.months[1])}</span>
    <h1>Every producing well,<br>one screen.</h1>
    <p class="lede">Production, decline, type curves, operators and inactive-well liability, built from public regulator data and refreshed every month.</p>
  </section>
  ${metricTiles(b, tile("rose", "Producing now", fmt.k(b.producing), META.counts.wells ? `${fmt.k(META.counts.wells)} wells on the provincial lists` : "wells and facilities reporting"))}
  <section class="grid2">
    <div class="card" style="display:grid;gap:10px"><div class="section-head"><h2>Production</h2><div class="chips" id="provChips"></div></div><div id="histChart"></div></div>
    <div class="card" style="display:grid;gap:10px"><h2>Producing base, forecast</h2><p class="muted" style="margin:0;font-size:14px">Wells online 12+ months, fitted with four decline shapes. Value in the PDP tile uses your price deck.</p><div id="fcChart"></div></div>
  </section>
  ${provs.length > 1 ? `<section class="tiles">${provs.map(([p, m]) => `<a class="tile t-${{ AB: "sky", SK: "butter", BC: "mint", MB: "lilac" }[p]}" style="text-decoration:none" href="#map"><span class="k">${PROV[p]}</span><span class="v">${fmt.k(m.boe)}</span><span class="s">boe/d · ${fmt.pct(m.oil_pct)} oil · decline ${fmt.pct(m.decline, 1)} · data to ${fmt.month(m.latest)}</span></a>`).join("")}</section>` : ""}
  <section class="card" style="display:grid;gap:10px"><div class="section-head"><h2>New-well type curve</h2><span class="muted" style="font-size:13px">boe/d per calendar day, aligned to first month of production</span></div><div id="tcChart"></div></section>
  <section class="card" style="display:grid;gap:12px"><div class="section-head"><h2>Largest operators</h2><a class="pill" href="#operators">All operators</a></div>${opsTable(BASIN.top_operators.slice(0, 12))}</section>
  ${BASIN.activity.years.length ? `<section class="card" style="display:grid;gap:10px"><h2>Wells spudded by year</h2><div id="actChart"></div><p class="muted" style="margin:0;font-size:13px">Horizontal share, latest year: ${fmt.pct(BASIN.activity.horizontal_share.at(-1))}</p></section>` : ""}
  ${footer()}`;
  const chips = $("#provChips");
  const opts = [["ALL", "Basin"], ...provs.map(([p]) => [p, p])];
  let sel = "ALL";
  const draw = () => {
    const m = sel === "ALL" ? b : BASIN.provinces[sel];
    chips.innerHTML = opts.length > 2 ? opts.map(([k, l]) => `<button class="chip ${k === sel ? "on" : ""}" data-k="${k}">${l}</button>`).join("") : "";
    chips.querySelectorAll("button").forEach((x) => x.onclick = () => { sel = x.dataset.k; draw(); });
    historyChart($("#histChart"), m.months, m.history.oil, m.history.gas);
    forecastChart($("#fcChart"), m.months.slice(-24), m.history.boe.slice(-24), m.pdp);
  };
  draw();
  typeCurveChart($("#tcChart"), b.type_curve_hz || b.type_curve, "--lilac-ink", b.type_curve_hz ? b.type_curve_vt : null);
  if (BASIN.activity.years.length) barsChart($("#actChart"), BASIN.activity.years, Object.entries(BASIN.activity.by_province).map(([p, vals]) => ({ name: PROV[p] || p, color: PCOL[p] || "--ink", values: vals })));
  bindOpRows(v);
}

function opsTable(list) {
  const mx = Math.max(...list.map((o) => o.boe || 0), 1);
  return `<div class="tablewrap"><table><thead><tr><th>Operator</th><th class="n">boe/d</th><th></th><th class="n">Oil %</th><th class="n">Decline</th><th class="n">New 12m</th><th class="n">PDP PV</th><th class="n">Inactive wells</th></tr></thead><tbody>
  ${list.map((o) => { const pv = pvRange(o.pdp); return `<tr data-op="${esc(o.id)}"><td><span class="opname">${esc(o.name)}</span><div>${Object.keys(o.prov || {}).map((p) => `<span class="tag ${p}">${p}</span>`).join(" ")}</div></td>
    <td class="n">${fmt.k(o.boe)}</td><td style="width:120px"><div class="bar"><i style="width:${(o.boe || 0) / mx * 100}%;background:${o.oil_pct > 50 ? "var(--oil)" : "var(--gas)"}"></i></div></td>
    <td class="n">${fmt.pct(o.oil_pct)}</td><td class="n">${fmt.decl(o.decline)}</td><td class="n">${fmt.n(o.new12)}</td>
    <td class="n">${fmt.pv(pv)}</td><td class="n">${o.inactive == null ? "–" : fmt.n(o.inactive)}</td></tr>`; }).join("")}
  </tbody></table></div>`;
}
function bindOpRows(root) { root.querySelectorAll("tr[data-op]").forEach((tr) => tr.onclick = () => { location.hash = "operator-" + tr.dataset.op; }); }

// ---- operators list
let opSort = { k: "boe", dir: -1 }, opQuery = "";
async function operatorsView() {
  OPS = OPS || await getJSON("operators.json");
  const v = $("#view");
  v.innerHTML = `<section style="display:grid;gap:10px"><span class="eyebrow">${fmt.n(OPS.length)} operators with production or inactive wells</span><h1>Operators</h1>
    <p class="lede">Ranked by current production. Tap one for its decline, type curve, PDP value at your deck and inactive-well liability.</p></section>
    <div style="display:flex;gap:10px;flex-wrap:wrap"><input class="search" id="opSearch" type="search" placeholder="Search operators" value="${esc(opQuery)}" aria-label="Search operators"></div>
    <section class="card"><div class="tablewrap"><table id="opTable"></table></div></section>${footer()}`;
  const cols = [["name", "Operator", 0], ["boe", "boe/d", 1], ["oil_pct", "Oil %", 1], ["decline", "Base decline", 1], ["new12", "New wells 12m", 1], ["ip90", "Median IP90", 1], ["wcut", "Water cut", 1], ["inactive", "Inactive wells", 1], ["cleanup", "Est. cleanup", 1]];
  const draw = () => {
    const q = opQuery.toLowerCase();
    const rows = OPS.filter((o) => !q || o.name.toLowerCase().includes(q)).sort((a, b) => {
      const x = a[opSort.k], y = b[opSort.k];
      if (typeof x === "string") return opSort.dir * x.localeCompare(y);
      return opSort.dir * ((x ?? -1e18) - (y ?? -1e18));
    }).slice(0, 300);
    $("#opTable").innerHTML = `<thead><tr>${cols.map(([k, l, n]) => `<th class="${n ? "n" : ""}" data-k="${k}">${l}${opSort.k === k ? (opSort.dir < 0 ? " ↓" : " ↑") : ""}</th>`).join("")}</tr></thead><tbody>
      ${rows.map((o) => `<tr data-op="${esc(o.id)}"><td><span class="opname">${esc(o.name)}</span> ${Object.keys(o.prov || {}).map((p) => `<span class="tag ${p}">${p}</span>`).join(" ")}</td>
      <td class="n">${fmt.k(o.boe)}</td><td class="n">${fmt.pct(o.oil_pct)}</td><td class="n">${fmt.decl(o.decline)}</td><td class="n">${fmt.n(o.new12)}</td><td class="n">${fmt.n(o.ip90)}</td><td class="n">${fmt.pct(o.wcut)}</td>
      <td class="n">${o.inactive == null ? "–" : fmt.n(o.inactive)}</td><td class="n">${o.cleanup ? fmt.money(o.cleanup) : "–"}</td></tr>`).join("")}</tbody>`;
    $("#opTable").querySelectorAll("th").forEach((th) => th.onclick = () => { opSort = { k: th.dataset.k, dir: opSort.k === th.dataset.k ? -opSort.dir : -1 }; draw(); });
    bindOpRows($("#opTable"));
  };
  $("#opSearch").addEventListener("input", (e) => { opQuery = e.target.value; draw(); });
  draw();
}

async function operatorView(id) {
  const v = $("#view");
  let o;
  try { o = await getJSON("operators/" + id + ".json"); } catch (e) { v.innerHTML = `<div class="empty">That operator isn't in this dataset. <a href="#operators">Back to operators</a></div>`; return; }
  const lb = o.liability;
  v.innerHTML = `<a class="pill" href="#operators" style="justify-self:start">← Operators</a>
    <section style="display:grid;gap:10px"><span class="eyebrow">Operator ${Object.keys(o.prov || {}).map((p) => `<span class="tag ${p}">${PROV[p]}</span>`).join(" ")}</span><h1>${esc(o.name)}</h1>
    <p class="lede">${fmt.n(o.producing)} producing wells or facilities, data through ${fmt.month(o.months.at(-1))}.</p></section>
    ${metricTiles(o, lb ? tile("rose", "Inactive wells", fmt.n(lb.inactive), `${fmt.n(lb.wells)} licensed · est. cleanup ${fmt.money(lb.cleanup)}`) : "")}
    <section class="grid2e"><div class="card" style="display:grid;gap:10px"><h2>Production</h2><div id="h"></div></div>
      <div class="card" style="display:grid;gap:10px"><h2>Producing base, forecast</h2><div id="f"></div>${pdpNote(o.pdp)}</div></section>
    <section class="card" style="display:grid;gap:10px"><div class="section-head"><h2>New-well type curve</h2><span class="muted" style="font-size:13px">${o.ip365 ? `Median first-year rate ${fmt.n(o.ip365)} boe/d` : ""}</span></div><div id="tc"></div></section>
    <section class="grid2e">
      <div class="card" style="display:grid;gap:10px;align-content:start"><h2>Where they produce</h2>${areaList(o.areas)}</div>
      <div class="card" style="display:grid;gap:10px;align-content:start"><h2>Licence liability</h2>${lb ? `<div class="kv">
        <div><span class="k">Wells licensed</span><span class="v">${fmt.n(lb.wells)}</span></div><div><span class="k">Producing (licence status)</span><span class="v">${fmt.n(lb.producing_lic)}</span></div>
        <div><span class="k">Inactive</span><span class="v">${fmt.n(lb.inactive)}</span></div><div><span class="k">Abandoned</span><span class="v">${fmt.n(lb.abandoned)}</span></div>
        <div><span class="k">Inactive share</span><span class="v">${fmt.pct(lb.wells ? lb.inactive / Math.max(lb.inactive + lb.producing_lic, 1) * 100 : null)}</span></div><div><span class="k">Est. cleanup, inactive wells</span><span class="v">${fmt.money(lb.cleanup)}</span></div></div>
        <p class="muted" style="margin:0;font-size:13px">Cleanup uses a placeholder per-well formula (base plus depth). It is not the AER's licensee capability assessment.</p>` : `<div class="empty">No well licences matched this operator's name.</div>`}</div></section>
    <section class="card" style="display:grid;gap:10px"><h2>Top wells and facilities</h2>${wellsTable(o.wells_list)}</section>${footer()}`;
  historyChart($("#h"), o.months, o.history.oil, o.history.gas);
  forecastChart($("#f"), o.months.slice(-24), o.history.boe.slice(-24), o.pdp);
  typeCurveChart($("#tc"), o.type_curve_hz || o.type_curve, "--lilac-ink", o.type_curve_hz ? o.type_curve_vt : null);
  v.querySelectorAll("[data-area]").forEach((a) => a.onclick = () => { location.hash = "area-" + a.dataset.area; });
}
function pdpNote(pdp) {
  const pv = pvRange(pdp);
  if (!pv) return "";
  return `<div class="kv"><div><span class="k">PV at your deck (${fmt.pct(DECK.discount * 100)} discount)</span><span class="v">${pv.nb <= 0 ? "Uneconomic (netback C$" + fmt.n(pv.nb, 2) + "/boe)" : fmt.money(pv.lo) + " to " + fmt.money(pv.hi)}</span></div>
    <div><span class="k">Remaining volume, 30-yr cap</span><span class="v">${fmt.k(pv.eur[0])} to ${fmt.k(pv.eur[1])} boe</span></div>
    <div><span class="k">Current base decline (fit)</span><span class="v">${fmt.decl(pdp.decl)}</span></div><div><span class="k">Fit quality r²</span><span class="v">${fmt.n(pdp.r2, 2)}</span></div></div>`;
}
function areaList(areas) {
  if (!areas || !areas.length) return `<div class="empty">No located production.</div>`;
  const byId = new Map(CELLS.map((c) => [c.id, c])), mx = Math.max(...areas.map((a) => a.boe));
  return `<div style="display:grid;gap:8px">${areas.slice(0, 12).map((a) => { const c = byId.get(a.id); return `<button class="pill" data-area="${a.id}" style="justify-content:space-between;width:100%;border-radius:12px">
    <span>${esc(c ? c.label : a.id)} ${c && c.prov ? `<span class="tag ${c.prov}">${c.prov}</span>` : ""}</span><span class="num">${fmt.k(a.boe)} boe/d</span></button>`; }).join("")}
    ${areas.length > 12 ? `<span class="muted" style="font-size:13px">and ${areas.length - 12} more areas</span>` : ""}</div>`;
}

// ---- map
const METRICS = {
  boe: { label: "Production (boe/d)", color: "--lilac-ink", get: (c) => c.boe, fmt: (v) => fmt.k(v) },
  oil_pct: { label: "Oil weighting", color: "--mint-ink", get: (c) => c.oil_pct, fmt: (v) => fmt.pct(v) },
  decline: { label: "Base decline", color: "--peach-ink", get: (c) => c.decline, fmt: (v) => fmt.decl(v) },
  new12: { label: "New wells, 12 months", color: "--sky-ink", get: (c) => c.new12, fmt: (v) => fmt.n(v) },
  inactive: { label: "Inactive wells", color: "--rose-ink", get: (c) => c.inactive, fmt: (v) => fmt.n(v) },
};
let MAP, LAYER, mapMetric = "boe", selectedArea = null;
function mix(hex, t) {   // blend a token colour with the background
  const a = css("--bg"), toRGB = (h) => { const m = h.replace("#", ""); return [0, 2, 4].map((i) => parseInt(m.slice(i, i + 2), 16)); };
  const A = toRGB(a), B = toRGB(hex);
  return "rgb(" + A.map((x, i) => Math.round(x + (B[i] - x) * t)).join(",") + ")";
}
async function mapView(areaId) {
  const v = $("#view");
  if (typeof L === "undefined") { v.innerHTML = `<div class="empty">The map library couldn't load. Check your connection and reload.</div>`; return; }
  if (!$("#map")) {
    v.innerHTML = `<section style="display:grid;gap:8px"><span class="eyebrow">${fmt.n(CELLS.length)} areas, each about one township</span><h1>Map</h1></section>
      <div style="display:flex;gap:10px;align-items:center;flex-wrap:wrap"><div class="chips" id="metricChips"></div><span class="spacer"></span><div class="scale" id="scale" style="min-width:220px"></div></div>
      <div class="mapwrap"><div id="map" role="region" aria-label="Map of production areas"></div><div class="panel" id="panel"></div></div>${footer()}`;
    MAP = L.map("map", { preferCanvas: true, zoomSnap: 0.5 });
    const dark = matchMedia("(prefers-color-scheme: dark)").matches && document.documentElement.dataset.theme !== "light";
    L.tileLayer(`https://{s}.basemaps.cartocdn.com/${dark ? "dark_all" : "light_all"}/{z}/{x}/{y}{r}.png`, {
      maxZoom: 14, attribution: '&copy; <a href="https://www.openstreetmap.org/copyright">OpenStreetMap</a> &copy; <a href="https://carto.com/attributions">CARTO</a>' }).addTo(MAP);
    const b = CELLS.filter((c) => c.boe > 0);
    const lats = b.flatMap((c) => [c.b[0], c.b[2]]), lons = b.flatMap((c) => [c.b[1], c.b[3]]);
    MAP.fitBounds([[Math.min(...lats), Math.min(...lons)], [Math.max(...lats), Math.max(...lons)]], { padding: [20, 20] });
    drawCells();
    if (!areaId) $("#panel").innerHTML = `<div class="card" style="display:grid;gap:10px"><h2>Pick an area</h2><p class="muted" style="margin:0">Tap any square for its production, decline forecast, type curve, operators and wells.</p>
      <h3 style="margin-top:6px">Top areas by production</h3>${areaList(CELLS.slice().sort((a, b) => b.boe - a.boe).slice(0, 10).map((c) => ({ id: c.id, boe: c.boe })))}</div>`;
    $("#panel").querySelectorAll("[data-area]").forEach((a) => a.onclick = () => { location.hash = "area-" + a.dataset.area; });
  }
  if (areaId) showArea(areaId);
}
function drawCells() {
  const m = METRICS[mapMetric];
  $("#metricChips").innerHTML = Object.entries(METRICS).map(([k, x]) => `<button class="chip ${k === mapMetric ? "on" : ""}" data-k="${k}">${x.label}</button>`).join("");
  $("#metricChips").querySelectorAll("button").forEach((b) => b.onclick = () => { mapMetric = b.dataset.k; drawCells(); });
  const vals = CELLS.map(m.get).filter((x) => x != null && isFinite(x)).sort((a, b) => a - b);
  const q = (p) => vals.length ? vals[Math.min(vals.length - 1, Math.floor(p * vals.length))] : 0;
  const breaks = [q(0.2), q(0.4), q(0.6), q(0.8)], col = css(m.color);
  const shade = (v) => v == null || !isFinite(v) ? null : mix(col, 0.18 + 0.82 * (breaks.filter((b) => v > b).length / 4));
  $("#scale").innerHTML = `<span style="background:linear-gradient(90deg,${mix(col, .18)},${col})"></span><span style="flex:none">${m.fmt(q(0))} – ${m.fmt(vals.at(-1))}</span>`;
  if (LAYER) LAYER.remove();
  LAYER = L.layerGroup().addTo(MAP);
  CELLS.forEach((c) => {
    const val = m.get(c), fill = shade(val);
    if (!fill || (mapMetric !== "inactive" && !c.boe)) return;
    L.rectangle([[c.b[0], c.b[1]], [c.b[2], c.b[3]]], { color: c.id === selectedArea ? css("--ink") : fill, weight: c.id === selectedArea ? 2.5 : 0.5,
      fillColor: fill, fillOpacity: 0.78 }).bindTooltip(`<b>${esc(c.label)}</b><br>${m.label}: ${m.fmt(val)}<br>${fmt.k(c.boe)} boe/d${c.top ? " · " + esc(c.top) : ""}`, { sticky: true })
      .on("click", () => { location.hash = "area-" + c.id; }).addTo(LAYER);
  });
}
async function showArea(id) {
  selectedArea = id; drawCells();
  const c = CELLS.find((x) => x.id === id);
  if (c) MAP.fitBounds([[c.b[0] - 0.15, c.b[1] - 0.25], [c.b[2] + 0.15, c.b[3] + 0.25]], { maxZoom: 10 });
  const p = $("#panel");
  p.innerHTML = `<div class="card"><p class="muted">Loading area…</p></div>`;
  let a;
  try { a = await getJSON("cells/" + id + ".json"); } catch (e) {
    p.innerHTML = `<div class="card" style="display:grid;gap:8px"><h2>${esc(c ? c.label : id)}</h2><p class="muted" style="margin:0">${c && c.inactive ? fmt.n(c.inactive) + " inactive wells, no reported production in this window." : "No production detail for this area."}</p></div>`; return;
  }
  const pv = pvRange(a.pdp);
  p.innerHTML = `<div class="card" style="display:grid;gap:14px">
      <div><span class="eyebrow">${a.prov ? PROV[a.prov] : ""} · ${a.b[0].toFixed(2)}°N ${Math.abs(a.b[1]).toFixed(2)}°W</span><h2 style="font-size:28px">${esc(a.label)}</h2></div>
      <div class="tiles" style="grid-template-columns:repeat(2,minmax(0,1fr))">
        ${tile("lilac", "Production", fmt.k(a.boe), "boe/d")}${tile("mint", "Oil weighting", fmt.pct(a.oil_pct), `GOR ${a.gor ? fmt.k(a.gor) : "–"} scf/bbl`)}
        ${tile("peach", "Base decline", fmt.decl(a.decline), "year over year")}${tile("sky", "PDP value", fmt.pv(pv), pv && pv.nb > 0 ? `range ${fmt.money(pv.lo)}–${fmt.money(pv.hi)}` : pv ? `netback C$${fmt.n(pv.nb, 2)}/boe at your deck` : "")}
      </div>
      <div class="kv"><div><span class="k">Producing</span><span class="v">${fmt.n(a.producing)}</span></div><div><span class="k">New wells, 12 months</span><span class="v">${fmt.n(a.new12)}</span></div>
        <div><span class="k">Water cut</span><span class="v">${fmt.pct(a.wcut)}</span></div><div><span class="k">Inactive wells</span><span class="v">${fmt.n(a.inactive)}</span></div></div></div>
    <div class="card" style="display:grid;gap:8px"><h3>Production and forecast</h3><div id="af"></div></div>
    <div class="card" style="display:grid;gap:8px"><h3>Type curve, new wells</h3><div id="at"></div></div>
    <div class="card" style="display:grid;gap:8px"><h3>Operators here</h3>${(a.operators || []).map((o) => `<div style="display:grid;gap:4px"><div style="display:flex;justify-content:space-between;gap:8px"><span class="opname">${esc(o.op)}</span><span class="num muted">${fmt.k(o.boe)} boe/d · ${fmt.pct(o.share)}</span></div><div class="bar"><i style="width:${o.share}%;background:var(--lilac-ink)"></i></div></div>`).join("") || `<div class="empty">No producing operators.</div>`}</div>
    <div class="card" style="display:grid;gap:8px"><h3>Wells and facilities</h3>${wellsTable(a.wells_list.slice(0, 40))}</div>`;
  forecastChart($("#af"), a.months.slice(-24), a.history.boe.slice(-24), a.pdp, 48);
  typeCurveChart($("#at"), a.type_curve);
  p.scrollTop = 0;
  if (innerWidth < 1000) p.scrollIntoView({ behavior: "smooth" });
}

function methodsView() {
  const m = META, bt = m.backtest, lc = m.location_check;
  $("#view").innerHTML = `<section style="display:grid;gap:10px"><span class="eyebrow">Generated ${esc(m.generated)}</span><h1>Data and methods</h1>
    <p class="lede">Every number comes from a public regulator file, converted the same way across provinces. Here's where it comes from and how much to trust it.</p></section>
    <section class="tiles">
      ${tile("lilac", "Wells on provincial lists", fmt.k(m.counts.wells))}${tile("mint", "Producing wells and facilities", fmt.k(m.counts.entities), `${fmt.pct(m.counts.well_level_share * 100)} reported as single wells`)}
      ${tile("sky", "Back-test error", bt ? fmt.pct(bt.median_abs_err, 1) : "–", bt ? `median, ${bt.n} areas, last 6 months held out` : "")}
      ${tile("butter", "DLS location error", lc ? lc.median_km + " km" : "–", lc ? `median vs surveyed, ${fmt.k(lc.n)} wells (p90 ${lc.p90_km} km)` : "Measured when surveyed coordinates load")}
    </section>
    <section class="card prose" style="display:grid;gap:12px"><h2>Sources</h2>
      <ul>${Object.entries(m.sources).map(([p, s]) => `<li><b>${esc(s.name)}</b>: ${s.pages.map((u) => `<a href="${esc(u)}" target="_blank" rel="noopener">${esc(u.replace("https://", ""))}</a>`).join(", ")}. Data through ${fmt.month(m.latest[p])}.</li>`).join("")}</ul>
      <p class="muted" style="font-size:14px">Alberta: AER ST37 well list and Petrinex Alberta public data. Saskatchewan: Petrinex Saskatchewan public data (the province's own well bundles are paid). BC: BC Energy Regulator well index and all-well production. Manitoba: Petroleum Branch well monthly production workbooks and weekly UWI list.</p></section>
    <section class="card prose" style="display:grid;gap:12px"><h2>Method</h2><ol class="steps">
      <li class="tile t-sky"><span class="k">1 · Normalise</span><span class="s">Oil and condensate in bbl/d, gas in mcf/d, per calendar day. boe = bbl + mcf ÷ 6. UWIs from every publisher are matched to one format.</span></li>
      <li class="tile t-mint"><span class="k">2 · Locate</span><span class="s">Surveyed coordinates where published (AER, BCER). Otherwise the legal location (DLS or NTS) is converted; the error is measured and shown above.</span></li>
      <li class="tile t-butter"><span class="k">3 · Decline</span><span class="s">Arps q = qᵢ/(1+b·Dᵢ·t)^(1/b) with a 6%/yr terminal tail, fitted at b = 0.3, 0.5, 0.8 and 1.0, reported as a range.</span></li>
      <li class="tile t-lilac"><span class="k">4 · Value</span><span class="s">Forecast × field netback from your price deck, discounted monthly. Pre-tax, producing wells only (PDP-style), 30-year cap.</span></li>
      <li class="tile t-peach"><span class="k">5 · Test</span><span class="s">Refit each area without its last 6 months and compare the forecast with what was reported.</span></li></ol></section>
    <section class="card prose" style="display:grid;gap:10px"><h2>Definitions</h2><ul>
      <li><b>Base decline</b>: last three months versus the same three months a year earlier, for wells online at least 15 months.</li>
      <li><b>Type curve</b>: new wells aligned to their first producing month. P10 is the high case (10% of wells do better), P90 the low case.</li>
      <li><b>IP90 / IP365</b>: average calendar-day boe/d over the first three and twelve months.</li>
      <li><b>Inactive wells</b>: suspended or shut-in on the provincial licence list. Cleanup is a placeholder of $80k plus $55 per metre of depth, not the regulator's liability rating.</li></ul></section>
    <section class="card prose" style="display:grid;gap:10px"><h2>Limits</h2><ul>
      <li>Public volumes are gross. Companies report working-interest volumes, so operator totals here won't match their filings exactly.</li>
      <li>Confidential wells are reported at facility level and can't be split by well.</li>
      <li>Values are pre-tax and ignore capital, abandonment timing and hedges. They are screening estimates, not reserves.</li>
      <li>Check each regulator's terms of use before commercial redistribution.</li></ul>
      ${m.problems && Object.keys(m.problems).length ? `<div class="banner"><div><b>Last run had problems:</b> ${Object.entries(m.problems).map(([k, v]) => `${esc(k)}: ${esc(v).slice(0, 160)}`).join("; ")}</div></div>` : ""}</section>${footer()}`;
}
function footer() {
  return `<footer><div>Sources: AER, Petrinex (Alberta and Saskatchewan public data), BC Energy Regulator, Manitoba Petroleum Branch. Screening estimates, not reserves.</div>
    <div>Data through ${fmt.month(META.months[1])} · generated ${esc(META.generated)} · <a href="https://github.com/kosherite/wellscope" target="_blank" rel="noopener">source on GitHub</a></div></footer>`;
}

// ------------------------------------------------------------------ router
async function route() {
  const h = location.hash.replace("#", "") || "overview";
  setNav(h);
  tip.hidden = true;
  try {
    if (h.startsWith("area-")) { setNav("map"); await mapView(h.slice(5)); return; }
    if (h === "map") { await mapView(); return; }
    MAP = null; LAYER = null;
    if (h === "operators") await operatorsView();
    else if (h.startsWith("operator-")) await operatorView(h.slice(9));
    else if (h === "methods") methodsView();
    else overview();
    if (!h.startsWith("area-")) scrollTo(0, 0);
  } catch (e) {
    console.error(e);
    $("#view").innerHTML = `<div class="empty">Something failed while loading this page: ${esc(e.message)}. Reload to try again.</div>`;
  }
}

(async function start() {
  try {
    [META, BASIN, CELLS] = await Promise.all([getJSON("meta.json"), getJSON("basin.json"), getJSON("cells.json")]);
  } catch (e) {
    $("#view").innerHTML = `<div class="empty">No data found in <span class="mono">site/data</span>. Run <span class="mono">python -m wellscope run</span> to build it.</div>`;
    return;
  }
  loadDeck(); renderDeck();
  const deck = $("#deck"), open = (o) => { deck.classList.toggle("open", o); deck.setAttribute("aria-hidden", String(!o)); };
  $("#deckBtn").onclick = () => open(true);
  $("#deckClose").onclick = () => open(false);
  $("#deckReset").onclick = () => { DECK = { ...META.price_deck }; saveDeck(); renderDeck(); route(); };
  addEventListener("keydown", (e) => { if (e.key === "Escape") open(false); });
  addEventListener("hashchange", () => { if (!location.hash.startsWith("#area-") || !$("#map")) route(); else mapView(location.hash.slice(6)); });
  route();
})();
