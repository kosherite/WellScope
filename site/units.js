/* Units and saved preferences. Data files hold rates per calendar day in bbl, mcf and boe;
   everything shown goes through UNITS so the Layers panel can switch metric/imperial and per day/per month. */
"use strict";

const PREFS = (() => {
  const KEY = "wellscope.prefs";
  let p = {};
  try { p = JSON.parse(localStorage.getItem(KEY) || "{}") || {}; } catch (e) { p = {}; }
  return {
    get: (k, dflt) => (p[k] === undefined ? dflt : p[k]),
    set: (k, v) => { p[k] = v; try { localStorage.setItem(KEY, JSON.stringify(p)); } catch (e) { /* private window */ } },
  };
})();

const UNITS = (() => {
  const BBL_PER_M3 = 6.28981, MCF_PER_E3M3 = 35.3147;
  const daysIn = (m) => (m ? new Date(+m.slice(0, 4), +m.slice(5, 7), 0).getDate() : 30.44);
  const sys = () => PREFS.get("units", "metric"), per = () => PREFS.get("per", "day");
  // kind: "liq" (oil, condensate, water; bbl/d in the data), "gas" (mcf/d), "boe" (boe/d)
  function rate(kind, x, month) {
    if (x == null || !isFinite(x)) return x;
    let y = x;
    if (sys() === "metric") y = kind === "gas" ? x / MCF_PER_E3M3 : x / BBL_PER_M3;   // boe -> m³OE (1 m³OE = 6.29 boe)
    return per() === "month" ? y * daysIn(month) : y;
  }
  const series = (kind, arr, months) => (arr || months.map(() => 0)).map((v, i) => rate(kind, v, months[i]));
  const name = (kind) => (sys() === "metric" ? { liq: "m³", gas: "e³m³", boe: "m³OE" } : { liq: "bbl", gas: "mcf", boe: "boe" })[kind];
  const unit = (kind) => name(kind) + (per() === "month" ? "/month" : "/d");
  // gas totals for a company read better in mmcf (imperial) / e³m³ (metric)
  const bigGas = (mcfPerDay, month) => (sys() === "metric" ? rate("gas", mcfPerDay, month) : rate("gas", mcfPerDay, month) / 1000);
  const bigGasUnit = () => (sys() === "metric" ? "e³m³" : "mmcf") + (per() === "month" ? "/month" : "/d");
  // cumulative volume of a per-day series over its months
  function total(kind, arr, months) {
    const vol = (arr || []).reduce((a, v, i) => a + v * daysIn(months[i]), 0);
    if (sys() === "metric") return kind === "gas" ? [vol / MCF_PER_E3M3, "e³m³"] : [vol / BBL_PER_M3, "m³"];
    return kind === "gas" ? [vol / 1000, "mmcf"] : [vol, "bbl"];
  }
  // more decimals for small numbers (a stripper well in m³/d)
  const fmt = (v) => (v == null || !isFinite(v) ? "–" : Math.abs(v) < 10 ? n(v, 1) : n(v));
  const axis = (v) => (Math.abs(v) >= 1e4 ? n(v / 1e3) + "k" : Math.abs(v) < 10 && v !== 0 ? n(v, 1) : n(v));
  return { rate, series, unit, name, bigGas, bigGasUnit, total, fmt, axis, sys, per };
})();
