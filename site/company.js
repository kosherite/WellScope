/* Company view: production by month, formations driving it, and drilling activity.
   Opens in the left panel over the map (which filters to the company's wells); "Expand" widens it for desk work. */
"use strict";

const CO = { current: null, tab: "production" };
const KIND = { licence: "Licence", spud: "Spud", rig_release: "Rig release", L: "Licence", S: "Spud", R: "Rig release" };
const fmtK = (v) => v == null || !isFinite(v) ? "–" : Math.abs(v) >= 1e4 ? (v / 1e3).toFixed(1) + "k" : n(v);
const pct = (v, d = 0) => v == null || !isFinite(v) ? "–" : (v > 0 ? "+" : v < 0 ? "−" : "") + n(Math.abs(v), d) + "%";
const monthLabel = (m) => { const [y, mm] = m.split("-").map(Number); return new Date(y, mm - 1, 1).toLocaleString("en-CA", { month: "short", year: "numeric" }); };
const mean = (a) => a.length ? a.reduce((x, y) => x + y, 0) / a.length : 0;

async function openCompany(i, { fit = true } = {}) {
  const c = OPS[i];
  if (!c) return;
  if (!HAS_CO) { setOperator(i, { fit }); return; }      // data built before company pages existed: plain filter
  const p = panel();
  p.hidden = false; p.classList.add("wide");
  setOperator(i, { fit, quiet: true });
  p.innerHTML = `<p class="muted">Loading ${esc(c.n)}…</p>`;
  let d = null;
  try { d = await getJSON(`co/${c.id}.json`); } catch (e) { /* small operators have no page */ }
  CO.current = { i, c, d };
  selected = null; map.setFilter("sel", ["==", ["get", "u"], ""]);
  setHash();
  renderCompany();
}
function closeCompany() {
  const p = panel(); p.classList.remove("wide", "full"); CO.current = null;
}

function renderCompany() {
  const { c, d } = CO.current, p = panel();
  const prov = d ? Object.entries(d.provinces || {}).sort((a, b) => b[1] - a[1]).map(([k]) => `<span class="pill-s">${k}</span>`).join("") : "";
  p.innerHTML = `
    <div class="ph"><div><div class="co-title">${c.t ? `<span class="ticker">${esc(c.t)}</span>` : ""}<h2 class="co-name">${esc(c.n)}</h2></div>
      <div class="name">${n(c.w)} wells · ${n(c.p)} producing ${prov}</div></div>
      <div class="ph-actions"><button class="x" id="coExpand" title="${p.classList.contains("full") ? "Back to map" : "Expand"}" aria-label="Expand">${p.classList.contains("full") ? "⤡" : "⤢"}</button><button class="x" id="coClose" aria-label="Close">×</button></div></div>
    ${d ? `<div class="tabs" role="tablist">${["production", "formations", "activity"].map((t) => `<button role="tab" data-t="${t}" class="${CO.tab === t ? "on" : ""}">${t[0].toUpperCase() + t.slice(1)}</button>`).join("")}</div>
      <div id="coBody"></div>` : `<p class="muted" style="margin:0">Not enough production or wells for a company page. The map shows their ${n(c.w)} wells.</p>`}`;
  $("#coClose").onclick = () => { closeCompany(); closePanel(); setOperator(null); };
  $("#coExpand").onclick = () => { p.classList.toggle("full"); renderCompany(); };
  p.querySelectorAll(".tabs button").forEach((b) => b.onclick = () => { CO.tab = b.dataset.t; renderCompany(); });
  if (!d) return;
  const body = $("#coBody");
  if (CO.tab === "production") renderProduction(body, d);
  else if (CO.tab === "formations") renderFormations(body, d);
  else renderActivity(body, d);
}

// ---- production
function renderProduction(body, d) {
  if (!d.prod) { body.innerHTML = `<p class="muted">No reported production in the last ${d.months.length} months.</p>`; return; }
  const { oil, cond, gas, wells } = d.prod, k = d.months.length;
  const boe = oil.map((o, i) => o + cond[i] + gas[i] / 6);
  const last3 = (a) => mean(a.slice(-3)), prev3 = (a) => mean(a.slice(-6, -3)), yago = (a) => mean(a.slice(-15, -12));
  const now = last3(boe), q = prev3(boe), y = yago(boe);
  const liquids = now > 0 ? (last3(oil) + last3(cond)) / now * 100 : null;
  body.innerHTML = `
    <div class="ctiles">
      <div class="ct t-lilac"><span>Production</span><b>${fmtK(now)}</b><small>boe/d, last 3 months</small></div>
      <div class="ct t-peach"><span>vs prior quarter</span><b>${pct(q > 0 ? (now / q - 1) * 100 : null, 1)}</b><small>${fmtK(q)} boe/d before</small></div>
      <div class="ct t-sky"><span>vs a year ago</span><b>${pct(y > 0 ? (now / y - 1) * 100 : null, 1)}</b><small>${fmtK(y)} boe/d then</small></div>
      <div class="ct t-mint"><span>Liquids</span><b>${liquids == null ? "–" : n(liquids) + "%"}</b><small>oil ${fmtK(last3(oil))} · cond ${fmtK(last3(cond))} bbl/d</small></div>
      <div class="ct t-butter"><span>Gas</span><b>${n(last3(gas) / 1000, 1)}</b><small>mmcf/d</small></div>
      <div class="ct t-rose"><span>Producing wells</span><b>${n(wells[k - 1])}</b><small>in ${monthLabel(d.months[k - 1])}</small></div>
    </div>
    <div class="chart" id="coChart"></div>
    <div class="key"><span><i style="background:var(--oil)"></i>Oil</span><span><i style="background:var(--cond)"></i>Condensate</span><span><i style="background:var(--gas)"></i>Gas (boe at 6:1)</span></div>
    <p class="src">Gross volumes from every well the company is licensee of, per calendar day, through ${monthLabel(d.months[k - 1])}. Companies report their working-interest share, so these won't match reported production exactly. Plant NGLs aren't reported at the well level.</p>`;
  stackedChart($("#coChart"), d.months, [["Oil", oil, css("--oil")], ["Condensate", cond, css("--cond")], ["Gas", gas.map((g) => g / 6), css("--gas")]], "boe/d",
    (i) => `<span>${n(wells[i])} producing wells · gas ${n(gas[i] / 1000, 1)} mmcf/d</span>`);
}

function stackedChart(host, months, series, unit, extra) {
  const W = 460, H = 200, L = 46, R = 10, T = 10, B = 22, k = months.length;
  const tot = months.map((_, i) => series.reduce((a, s) => a + (s[1][i] || 0), 0));
  const niceMax = (v) => { if (!(v > 0)) return 1; const p = 10 ** Math.floor(Math.log10(v)), q = v / p; return (q <= 1 ? 1 : q <= 2 ? 2 : q <= 2.5 ? 2.5 : q <= 5 ? 5 : 10) * p; };
  const ym = niceMax(Math.max(...tot, 1)), x = (i) => L + i / Math.max(k - 1, 1) * (W - L - R), y = (v) => T + (H - T - B) * (1 - v / ym);
  let base = months.map(() => 0), paths = "";
  series.forEach(([, vals, col]) => {
    const top = base.map((b, i) => b + (vals[i] || 0));
    paths += `<path d="M${top.map((v, i) => `${x(i).toFixed(1)},${y(v).toFixed(1)}`).join(" L")} L${base.map((v, i) => `${x(k - 1 - i).toFixed(1)},${y(base[k - 1 - i]).toFixed(1)}`).join(" L")} Z" fill="${col}" fill-opacity=".85"/>`;
    base = top;
  });
  let grid = "";
  for (let g = 0; g <= 4; g++) { const v = ym * g / 4; grid += `<line class="g" x1="${L}" x2="${W - R}" y1="${y(v)}" y2="${y(v)}"/><text x="${L - 6}" y="${y(v) + 3}" text-anchor="end">${fmtK(v)}</text>`; }
  let ticks = ""; months.forEach((m, i) => { if (m.endsWith("-01")) ticks += `<text x="${x(i)}" y="${H - 5}" text-anchor="middle">${m.slice(0, 4)}</text>`; });
  host.innerHTML = `<svg viewBox="0 0 ${W} ${H}" role="img" aria-label="Monthly production">${grid}${paths}${ticks}
    <line class="guide" y1="${T}" y2="${H - B}" stroke="${css("--ink")}" stroke-dasharray="2 3" style="display:none"/>
    <rect x="${L}" y="${T}" width="${W - L - R}" height="${H - T - B}" fill="transparent"/></svg><div class="ctip" hidden></div>`;
  const svg = host.querySelector("svg"), guide = svg.querySelector(".guide"), tip = host.querySelector(".ctip");
  const show = (cx) => {
    const r = svg.getBoundingClientRect(), i = Math.max(0, Math.min(k - 1, Math.round(((cx - r.left) / r.width * W - L) / (W - L - R) * (k - 1))));
    guide.style.display = ""; guide.setAttribute("x1", x(i)); guide.setAttribute("x2", x(i));
    tip.hidden = false;
    tip.innerHTML = `<b>${monthLabel(months[i])} · ${fmtK(tot[i])} ${unit}</b>${series.map(([nm, v, col]) => `<span><i style="background:${col}"></i>${nm} ${fmtK(v[i])}</span>`).join("")}${extra ? extra(i) : ""}`;
    tip.style.left = Math.max(0, Math.min(r.width - tip.offsetWidth, x(i) / W * r.width - tip.offsetWidth / 2)) + "px";
  };
  svg.addEventListener("pointermove", (e) => show(e.clientX));
  svg.addEventListener("pointerdown", (e) => show(e.clientX));
  svg.addEventListener("pointerleave", () => { guide.style.display = "none"; tip.hidden = true; });
}

// ---- formations
function renderFormations(body, d) {
  const rows = d.formations || [];
  if (!rows.length) { body.innerHTML = `<p class="muted">No producing formations to show.</p>`; return; }
  const total = rows.reduce((a, r) => a + r.boe, 0), dq = rows.reduce((a, r) => a + (r.boe - r.prev_q), 0);
  const spark = (s) => { const mx = Math.max(...s, 1e-9), w = 80, h = 22; return `<svg width="${w}" height="${h}" viewBox="0 0 ${w} ${h}" aria-hidden="true"><path d="M${s.map((v, i) => `${(i / Math.max(s.length - 1, 1) * w).toFixed(1)},${(h - 2 - v / mx * (h - 4)).toFixed(1)}`).join(" L")}" fill="none" stroke="${css("--accent")}" stroke-width="1.5"/></svg>`; };
  body.innerHTML = `
    <p class="lead">Quarter over quarter the company moved <b>${pct(total - dq > 0 ? dq / (total - dq) * 100 : null, 1)}</b> (${dq >= 0 ? "+" : "−"}${fmtK(Math.abs(dq))} boe/d). Each row shows how much of that came from the formation.</p>
    <div class="tablewrap"><table class="ftable"><thead><tr><th>Formation</th><th class="n">boe/d</th><th class="n">Share</th><th class="n">vs prior qtr</th><th class="n">Share of change</th><th class="n">vs year ago</th><th class="n">Liquids</th><th class="n">Wells</th><th>36 months</th></tr></thead>
    <tbody>${rows.slice(0, 25).map((r) => { const ch = r.boe - r.prev_q; return `<tr>
      <td><b>${esc(r.play)}</b></td><td class="n">${fmtK(r.boe)}</td>
      <td class="n"><span class="bar"><i style="width:${total ? r.boe / total * 100 : 0}%"></i></span>${total ? n(r.boe / total * 100) : 0}%</td>
      <td class="n ${ch > 0 ? "up" : ch < 0 ? "down" : ""}">${pct(r.prev_q > 0 ? (r.boe / r.prev_q - 1) * 100 : null, 1)}</td>
      <td class="n">${dq ? n(ch / Math.abs(dq) * 100) + "%" : "–"}</td>
      <td class="n">${pct(r.year_ago > 0 ? (r.boe / r.year_ago - 1) * 100 : null, 1)}</td>
      <td class="n">${r.liquids_pct == null ? "–" : r.liquids_pct + "%"}</td><td class="n">${n(r.wells)}</td><td>${spark(r.series)}</td></tr>`; }).join("")}</tbody></table></div>
    <p class="src">Last three months against the three before them, and against the same three months a year earlier. Formations come from each well's pool; wells reporting production but missing from the well lists show as Unassigned. Commingled means a well producing from several zones at once, which Alberta reports as a single pool.</p>`;
}

// ---- activity
function renderActivity(body, d) {
  const a = d.activity;
  if (!a) { body.innerHTML = `<p class="muted">No new licences or drilling starts in the last year.</p>`; return; }
  const sum = (arr, nW) => (arr || []).slice(-nW).reduce((x, y) => x + y, 0);
  const drill = a.weeks.map((_, i) => (a.spud?.[i] || 0) + (a.rig_release?.[i] || 0));
  body.innerHTML = `
    <div class="ctiles">
      <div class="ct t-lilac"><span>Licences, 13 weeks</span><b>${n(sum(a.licence, 13))}</b><small>${n(sum(a.licence, 52))} in 52 weeks</small></div>
      <div class="ct t-peach"><span>Drilling starts, 13 weeks</span><b>${n(sum(drill, 13))}</b><small>${n(sum(drill, 52))} in 52 weeks</small></div>
      <div class="ct t-sky"><span>Horizontal share</span><b>${a.recent.length ? n(a.recent.filter((r) => r[5]).length / a.recent.length * 100) + "%" : "–"}</b><small>of recent events</small></div>
    </div>
    <div class="chart" id="actChart"></div>
    <div class="key"><span><i style="background:var(--accent)"></i>Licences issued</span><span><i style="background:var(--spud)"></i>Drilling starts (spud; rig release in BC)</span></div>
    <h3 class="sub">Most recent</h3>
    <div class="evlist">${a.recent.slice(0, 40).map((r, i) => `<button data-i="${i}"><span class="evk ${r[1]}">${esc(KIND[r[1]] || r[1])}</span>
      <span><b class="mono">${esc(r[3])}</b><br><small class="muted">${esc(r[0])} · ${esc(r[2])}${r[4] ? " · " + esc(r[4]) : ""}${r[5] ? " · horizontal" : ""}</small></span></button>`).join("")}</div>
    <p class="src">Licences from Petrinex (Alberta, Saskatchewan) and the Manitoba Petroleum Branch; drilling starts from the provincial well lists, which update monthly.</p>`;
  barChart($("#actChart"), a.weeks, [["Licences", a.licence, css("--accent")], ["Drilling starts", drill, css("--spud")]]);
  body.querySelectorAll(".evlist button").forEach((b) => b.onclick = () => {
    const r = a.recent[+b.dataset.i];
    if (r[6] != null) { if (!$("#actT").checked) { $("#actT").checked = true; setActivity(true); } map.flyTo({ center: [r[6], r[7]], zoom: 13 }); }
  });
}
function barChart(host, weeks, series) {
  const W = 460, H = 150, L = 30, R = 6, T = 8, B = 20, k = weeks.length, bw = (W - L - R) / k;
  const mx = Math.max(...weeks.map((_, i) => series.reduce((a, s) => a + (s[1][i] || 0), 0)), 1);
  const y = (v) => T + (H - T - B) * (1 - v / mx);
  let bars = "";
  weeks.forEach((_, i) => { let acc = 0; series.forEach(([, v, col]) => { const h = v[i] || 0; if (h) bars += `<rect x="${(L + i * bw + 0.5).toFixed(1)}" y="${y(acc + h).toFixed(1)}" width="${Math.max(bw - 1, 1).toFixed(1)}" height="${(y(acc) - y(acc + h)).toFixed(1)}" fill="${col}" rx="1"/>`; acc += h; }); });
  let ticks = ""; weeks.forEach((w, i) => { if (i % 13 === 0) ticks += `<text x="${L + i * bw}" y="${H - 5}">${monthLabel(w.slice(0, 7))}</text>`; });
  host.innerHTML = `<svg viewBox="0 0 ${W} ${H}" role="img" aria-label="Weekly activity"><line class="g" x1="${L}" x2="${W - R}" y1="${y(mx)}" y2="${y(mx)}"/><text x="${L - 4}" y="${y(mx) + 3}" text-anchor="end">${n(mx)}</text>
    <line class="g" x1="${L}" x2="${W - R}" y1="${y(0)}" y2="${y(0)}"/>${bars}${ticks}<rect x="${L}" y="${T}" width="${W - L - R}" height="${H - T - B}" fill="transparent"/></svg><div class="ctip" hidden></div>`;
  const svg = host.querySelector("svg"), tip = host.querySelector(".ctip");
  svg.addEventListener("pointermove", (e) => {
    const r = svg.getBoundingClientRect(), i = Math.max(0, Math.min(k - 1, Math.floor(((e.clientX - r.left) / r.width * W - L) / bw)));
    tip.hidden = false; tip.innerHTML = `<b>Week of ${weeks[i]}</b>${series.map(([nm, v, col]) => `<span><i style="background:${col}"></i>${nm} ${n(v[i] || 0)}</span>`).join("")}`;
    tip.style.left = Math.max(0, Math.min(r.width - tip.offsetWidth, (L + i * bw) / W * r.width - tip.offsetWidth / 2)) + "px";
  });
  svg.addEventListener("pointerleave", () => { tip.hidden = true; });
}

// ------------------------------------------------------------------ activity layer on the map
let ACT = null;
async function setActivity(on) {
  if (!map.getSource("act")) {
    let data = { rows: [] };
    try { data = await getJSON("activity.json"); } catch (e) { toast("Activity data isn't available yet."); }
    ACT = data;
    const feats = (data.rows || []).map(([x, y, k, dt, cid, cname, label, fm, hz, pv]) => ({ type: "Feature", geometry: { type: "Point", coordinates: [x, y] },
      properties: { k, dt, c: cid, cn: cname, l: label, fm, hz, pv } }));
    map.addSource("act", { type: "geojson", data: { type: "FeatureCollection", features: feats } });
    map.addLayer({ id: "act", type: "circle", source: "act", paint: {
      "circle-radius": ["interpolate", ["linear"], ["zoom"], 4, 2.5, 9, 5, 14, 8],
      "circle-color": ["match", ["get", "k"], "L", "rgba(0,0,0,0)", css("--spud")],
      "circle-stroke-color": ["match", ["get", "k"], "L", css("--accent"), "#ffffff"],
      "circle-stroke-width": ["match", ["get", "k"], "L", 2.2, 1.2] } });
    map.on("click", "act", (e) => {
      const f = e.features[0].properties;
      new maplibregl.Popup({ closeButton: true, maxWidth: "280px" }).setLngLat(e.lngLat).setHTML(
        `<div class="pop"><span class="evk ${f.k}">${KIND[f.k]}</span> <b>${esc(f.dt)}</b><br><b class="mono">${esc(f.l)}</b><br>${esc(f.cn)}${f.fm ? "<br><span class='muted'>" + esc(f.fm) + "</span>" : ""}${+f.hz ? " · horizontal" : ""}
          <br><button class="link" data-c="${esc(f.c)}">Open company</button></div>`).addTo(map);
      setTimeout(() => document.querySelectorAll(".pop [data-c]").forEach((b) => b.onclick = () => { const i = OPS.findIndex((o) => o.id === b.dataset.c); if (i >= 0) openCompany(i); }), 0);
    });
    map.on("mouseenter", "act", () => { map.getCanvas().style.cursor = "pointer"; });
    map.on("mouseleave", "act", () => { map.getCanvas().style.cursor = ""; });
    const cnt = $("#actCount"); if (cnt) cnt.textContent = n((data.rows || []).length);
  }
  map.setLayoutProperty("act", "visibility", on ? "visible" : "none");
  applyActivityFilter();
}
function applyActivityFilter() {
  if (!map.getLayer("act")) return;
  map.setFilter("act", opFilter ? ["==", ["get", "c"], opFilter.id] : null);
}
