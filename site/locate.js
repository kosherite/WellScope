/* Survey-system helpers shared by search, the grid overlay and the well panel.
   Mirrors wellscope/locate.py and wellscope/mapdata.py so the browser and the pipeline agree. */
"use strict";
const LOC = (() => {
  const MER = { 1: 97.4579, 2: 102.0, 3: 106.0, 4: 110.0, 5: 114.0, 6: 118.0 };
  const TWP_KM = 9.656064, SEC_KM = TWP_KM / 6, KM_LAT = 111.2, LAT0 = 49.0;
  const kmLon = (lat) => 111.32 * Math.cos(lat * Math.PI / 180);
  const snake = (i, n) => { const r = Math.floor(i / n); return [r, r % 2 === 0 ? i % n : n - 1 - (i % n)]; };

  // ---- DLS
  function dlsToLatLon(lsd, sec, twp, rge, mer) {
    const [sr, sc] = snake(sec - 1, 6);
    let n, w;
    if (lsd) { const [lr, lc] = snake(lsd - 1, 4); n = (twp - 1) * TWP_KM + sr * SEC_KM + (lr + 0.5) * SEC_KM / 4; w = (rge - 1) * TWP_KM + sc * SEC_KM + (lc + 0.5) * SEC_KM / 4; }
    else if (sec) { n = (twp - 1) * TWP_KM + (sr + 0.5) * SEC_KM; w = (rge - 1) * TWP_KM + (sc + 0.5) * SEC_KM; }
    else { n = (twp - 0.5) * TWP_KM; w = (rge - 0.5) * TWP_KM; }
    const lat = LAT0 + n / KM_LAT;
    return [lat, -(MER[mer] + w / kmLon(lat))];
  }
  /** Corner of a township/range grid point: north km and west km from the meridian -> [lon, lat]. */
  function gridPoint(mer, northKm, westKm) {
    const lat = LAT0 + northKm / KM_LAT;
    return [-(MER[mer] + westKm / kmLon(lat)), lat];
  }
  /** Which township/range/meridian a lat/lon falls in (approximate inverse). */
  function fromLatLon(lat, lon) {
    const west = -lon;
    let mer = null;
    for (let m = 6; m >= 1; m--) if (west >= MER[m]) { mer = m; break; }
    if (!mer || lat < LAT0) return null;
    const n = (lat - LAT0) * KM_LAT, w = (west - MER[mer]) * kmLon(lat);
    return { mer, twp: Math.floor(n / TWP_KM) + 1, rge: Math.floor(w / TWP_KM) + 1, n, w };
  }

  // ---- NTS (BC)
  function ntsToLatLon(qu, unit, block, map, letter, sheet) {
    const series = Math.floor(map / 10), area = map % 10;
    let lat = 40 + 4 * area, lon = 48 + 8 * series;
    const L = "ABCDEFGHIJKLMNOP".indexOf(letter);
    let [r, c] = snake(L, 4); lat += r; lon += c * 2;
    [r, c] = snake(sheet - 1, 4); lat += r * 0.25; lon += c * 0.5;
    [r, c] = snake("ABCDEFGHIJKL".indexOf(block), 4); lat += r * 5 / 60; lon += c * 7.5 / 60;
    [r, c] = snake(unit - 1, 10); lat += r * 0.5 / 60; lon += c * 0.75 / 60;
    const q = { A: [0, 0], B: [0, 1], C: [1, 1], D: [1, 0] }[qu] || [0, 0];
    lat += (q[0] + 0.5) * 0.25 / 60; lon += (q[1] + 0.5) * 0.375 / 60;
    return [lat, -lon];
  }

  // ---- parsing what people type
  const RE_DLS = /^(?:(\d)?([0-9A-Z]{2})[\/.])?(?:(\d{1,2})-)?(\d{1,2})-(\d{1,3})-(\d{1,2})\s*W\s*(\d)(?:[\/.](\d{1,2}))?$/i;
  const RE_DLS_COMPACT = /^(?:[A-Z]{2}WI)?(\d)([0-9A-Z]{2})(\d{2})(\d{2})(\d{3})(\d{2})W(\d)(\d{1,2})$/i;
  const RE_TWP = /^T?\s*(\d{1,3})\s*[-\s]?\s*R?\s*(\d{1,2})\s*[-\s]?\s*W\s*(\d)$/i;
  const RE_NTS = /^(?:(\d)?([0-9A-Z]{2})\/)?([A-D])-?(\d{1,3})-?([A-L])\s*\/\s*(\d{2,3})-?([A-P])-?(\d{1,2})(?:\/(\d{1,2}))?$/i;
  const RE_NTS_COMPACT = /^(?:[A-Z]{2}WI)?(\d)([0-9A-Z]{2})([A-D])(\d{3})([A-L])(\d{3})([A-P])(\d{2})(\d{1,2})$/i;
  const z2 = (v) => String(v).padStart(2, "0"), z3 = (v) => String(v).padStart(3, "0");

  /** Parse any UWI or legal location. Returns {kind, canon?, key?, lat, lon, label, zoom} or null. */
  function parse(text) {
    const s = String(text || "").trim().toUpperCase().replace(/\s+/g, "");
    if (!s) return null;
    let m = s.match(RE_DLS_COMPACT);
    if (m) return dls(m[2], +m[3], +m[4], +m[5], +m[6], +m[7], m[8], true);
    m = s.match(RE_NTS_COMPACT);
    if (m) return nts(m[2], m[3], +m[4], m[5], +m[6], m[7], +m[8], m[9], true);
    m = s.match(RE_DLS);
    if (m) return dls(m[2], m[3] ? +m[3] : null, +m[4], +m[5], +m[6], +m[7], m[8], !!m[2] || !!m[8]);
    m = s.match(RE_NTS);
    if (m) return nts(m[2], m[3], +m[4], m[5], +m[6], m[7], +m[8], m[9], !!m[2] || !!m[9]);
    m = String(text).trim().toUpperCase().match(RE_TWP);
    if (m) {
      const [twp, rge, mer] = [+m[1], +m[2], +m[3]];
      if (!MER[mer] || twp < 1 || twp > 130 || rge < 1 || rge > 34) return null;
      const [lat, lon] = dlsToLatLon(null, null, twp, rge, mer);
      return { kind: "township", lat, lon, zoom: 11.5, label: `Township ${z3(twp)}-${z2(rge)}W${mer}` };
    }
    return null;
  }
  function dls(le, lsd, sec, twp, rge, mer, es, isUwi) {
    if (!MER[mer] || sec < 1 || sec > 36 || twp < 1 || twp > 130 || rge < 1 || rge > 34 || (lsd && (lsd < 1 || lsd > 16))) return null;
    const [lat, lon] = dlsToLatLon(lsd, sec, twp, rge, mer);
    const loc = `${lsd ? z2(lsd) + "-" : ""}${z2(sec)}-${z3(twp)}-${z2(rge)}W${mer}`;
    if (isUwi && lsd) {
      const canon = `${(le || "00").slice(-2)}/${loc}/${String(es ?? "0").slice(-1)}`;
      return { kind: "uwi", canon, key: `W${mer}-${z3(twp)}-${z2(rge)}`, lat, lon, zoom: 15, label: display(canon) };
    }
    return { kind: lsd ? "lsd" : "section", lat, lon, zoom: lsd ? 15 : 13.5, label: (lsd ? "LSD " : "Section ") + loc,
             key: `W${mer}-${z3(twp)}-${z2(rge)}`, loc };
  }
  function nts(le, qu, unit, block, map, letter, sheet, es) {
    if (unit < 1 || unit > 100 || sheet < 1 || sheet > 16) return null;
    const [lat, lon] = ntsToLatLon(qu, unit, block, map, letter, sheet);
    const loc = `${qu}-${z3(unit)}-${block}/${z3(map)}-${letter}-${z2(sheet)}`;
    const canon = `${(le || "00").slice(-2)}/${loc}/${String(es ?? "0").slice(-1)}`;
    return { kind: "uwi", canon, key: `N${z3(map)}${letter}${z2(sheet)}`, lat, lon, zoom: 15, label: display(canon) };
  }
  /** Canonical key -> the 16-character UWI people type. */
  function display(canon) {
    if (!canon || !canon.includes("/")) return canon;
    const parts = canon.split("/"), le = parts[0], es = parts.at(-1), mid = parts.slice(1, -1).join("/");
    return `${/^[A-D]-/.test(mid) ? "2" : "1"}${le}/${mid}/0${es}`;
  }
  function keyOf(canon) {
    let m = canon && canon.match(/^[0-9A-Z]{2}\/\d{2}-\d{2}-(\d{3})-(\d{2})W(\d)\/\d$/);
    if (m) return `W${m[3]}-${m[1]}-${m[2]}`;
    m = canon && canon.match(/^[0-9A-Z]{2}\/[A-D]-\d{3}-[A-L]\/(\d{3})-([A-P])-(\d{2})\/\d$/);
    return m ? `N${m[1]}${m[2]}${m[3]}` : null;
  }
  return { parse, display, keyOf, dlsToLatLon, gridPoint, fromLatLon, MER, TWP_KM, SEC_KM };
})();
