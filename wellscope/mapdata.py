"""Everything the map website needs, written as static files.

* ``wells.geojsonl`` / ``laterals.geojsonl``: one feature per line, fed to tippecanoe to make ``wells.pmtiles``.
  Features carry only what's needed to draw and filter them: UWI, symbol class, operator index, current rate.
* ``twp/<key>.json``: full well records and 36-month production, grouped by township (DLS) or map sheet (NTS).
  The key is derived from the UWI itself, so the browser can find any well's record from the UWI alone.
  Short keys keep files small: u uwi, d display UWI, p province, n name, li licence, lc licensee, st status text,
  sg status group, sd status date, fl fluid, fd field, fm formation/pool, sp spud or rig-release date, td total depth (m),
  hz horizontal, y/x surface lat/lon, lp location precision, by/bx bottom-hole lat/lon, s map symbol, b current boe/d,
  pr production [oil bbl/d, gas mcf/d, water bbl/d] per month (calendar-day rates).
* ``lic/<xx>.json``: licence number -> UWIs, sharded by the licence's last two characters.
* ``operators.json``: operator names with well counts and a bounding box, for search and filtering.
* ``meta.json``: data dates, counts and sources.
"""
from __future__ import annotations

import json
import math
import re
from collections import defaultdict
from pathlib import Path

import numpy as np
import pandas as pd

from . import locate
from .config import E3M3_TO_MCF, M3_TO_BBL
from .schema import WELL_COLS, canon_uwi

# Map symbols follow the usual well-map conventions: producing oil, producing gas, suspended oil/gas,
# abandoned, dry and abandoned, service (injection/disposal/source) and licensed or drilling.
SYMBOLS = {
    "oil": "Oil, producing", "gas": "Gas, producing", "oil_susp": "Oil, suspended", "gas_susp": "Gas, suspended",
    "aband": "Abandoned", "dry": "Dry and abandoned", "service": "Injection, disposal or source",
    "pre": "Licensed or drilling", "other": "Other or unknown",
}

_DLS_KEY = re.compile(r"^[0-9A-Z]{2}/\d{2}-\d{2}-(\d{3})-(\d{2})W(\d)/\d$")
_NTS_KEY = re.compile(r"^[0-9A-Z]{2}/[A-D]-\d{3}-[A-L]/(\d{3})-([A-P])-(\d{2})/\d$")


def shard_key(uwi: str | None) -> str | None:
    """Township (DLS) or map sheet (NTS) a UWI sits in; the website computes the same key in JavaScript."""
    if not isinstance(uwi, str):
        return None
    m = _DLS_KEY.match(uwi)
    if m:
        return f"W{m.group(3)}-{m.group(1)}-{m.group(2)}"
    m = _NTS_KEY.match(uwi)
    if m:
        return f"N{m.group(1)}{m.group(2)}{m.group(3)}"
    return None


def display_uwi(c: str | None) -> str | None:
    """Canonical key -> the 16-character form people type: 00/06-06-001-01W4/0 -> 100/06-06-001-01W4/00."""
    if not isinstance(c, str) or "/" not in c:
        return c
    le, mid, es = c.split("/")[0], "/".join(c.split("/")[1:-1]), c.split("/")[-1]
    survey = "2" if re.match(r"^[A-D]-", mid) else "1"
    return f"{survey}{le}/{mid}/0{es}"


def symbol(group: str, fluid: str, ever_produced: bool, text: str = "") -> str:
    oilish = fluid in ("Oil", "Bitumen")
    gasish = fluid == "Gas"
    if group == "Producing":
        return "gas" if gasish else "oil" if oilish else "oil" if ever_produced else "other"
    if group == "Inactive":
        return "gas_susp" if gasish else "oil_susp" if oilish else "other"
    if group == "Abandoned":
        t = str(text or "").upper()
        # Regulators rarely say "dry" outright; most abandoned wells list no fluid, so default to plain abandoned.
        return "dry" if ("DRY" in t or "D&A" in t or "D & A" in t) else "aband"
    if group == "Service":
        return "service"
    if group == "Pre-production":
        return "pre"
    return "other"


def grid_offsets(w: pd.DataFrame) -> tuple[dict, dict | None]:
    """Median (dlat, dlon) per DLS township between surveyed surface coordinates and the survey formula.

    The formula ignores road allowances and correction lines, so it drifts by up to a few km; shifting each
    township by its measured offset brings the drawn grid and formula-placed wells back over the real LSDs.
    """
    s = w[w["loc_precision"].eq("surveyed") & w["surface_loc"].notna()][["surface_loc", "lat", "lon"]]
    if s.empty:
        return {}, None
    rows = []
    for loc, la, lo in s.itertuples(index=False):
        d = locate.parse_dls(loc)
        if not d or not d.lsd:
            continue
        fy, fx = locate.dls_to_latlon(d)
        rows.append((f"W{d.mer}-{d.twp:03d}-{d.rge:02d}", la - fy, lo - fx, la))
    df = pd.DataFrame(rows, columns=["k", "dy", "dx", "lat"])
    df = df[(df["dy"].abs() < 0.1) & (df["dx"].abs() < 0.15)]           # drop misfiled locations
    g = df.groupby("k").agg(dy=("dy", "median"), dx=("dx", "median"), n=("dy", "size"))
    g = g[g["n"] >= 3]
    offsets = {k: [round(float(r.dy), 5), round(float(r.dx), 5)] for k, r in g.iterrows()}
    # residual error after the correction, on the same wells
    m = df.join(g[["dy", "dx"]], on="k", rsuffix="_t").dropna()
    before = np.hypot(m["dy"] * 111.2, m["dx"] * 111.32 * np.cos(np.radians(m["lat"])))
    after = np.hypot((m["dy"] - m["dy_t"]) * 111.2, (m["dx"] - m["dx_t"]) * 111.32 * np.cos(np.radians(m["lat"])))
    check = {"wells": int(len(m)), "townships": len(offsets), "median_km_before": round(float(before.median()), 2),
             "median_km_after": round(float(after.median()), 2), "p90_km_after": round(float(after.quantile(0.9)), 2)}
    return offsets, check


def _clean(v):
    if v is None or (isinstance(v, float) and not math.isfinite(v)):
        return None
    if v is pd.NA or v is pd.NaT:
        return None
    if isinstance(v, (np.floating,)):
        return None if not np.isfinite(v) else round(float(v), 5)
    if isinstance(v, (np.integer,)):
        return int(v)
    if isinstance(v, (np.bool_,)):
        return bool(v)
    if isinstance(v, pd.Timestamp):
        return v.strftime("%Y-%m-%d")
    return v


def build(wells: pd.DataFrame, prod: pd.DataFrame, out: Path, sources: dict, work: Path) -> dict:
    out, work = Path(out), Path(work)
    for d in (out / "twp", out / "lic", work):
        d.mkdir(parents=True, exist_ok=True)

    # ---- production: calendar-day rates per well and month
    p = prod[prod["entity_type"] == "well"].copy()
    days = p["month"].dt.days_in_month.astype("float32")
    p["oil"] = ((p["oil_m3"] + p["cond_m3"]) * M3_TO_BBL / days).round(1)
    p["gas"] = (p["gas_e3m3"] * E3M3_TO_MCF / days).round(1)
    p["wat"] = (p["water_m3"] * M3_TO_BBL / days).round(1)
    latest = p.groupby("province")["month"].max()
    months = sorted(p["month"].unique())
    mlabels = [pd.Timestamp(m).strftime("%Y-%m") for m in months]
    midx = {m: i for i, m in enumerate(months)}
    p["mi"] = p["month"].map(midx)
    last3 = p[p["month"] > p["province"].map(latest) - pd.DateOffset(months=3)]
    cur = last3.groupby("entity_id").agg(oil=("oil", "mean"), gas=("gas", "mean"))
    cur_boe = (cur["oil"] + cur["gas"] / 6).round(1)
    prod_op = p.sort_values("month").groupby("entity_id")["operator"].last()
    produced = set(p.loc[(p["oil"] > 0) | (p["gas"] > 0), "entity_id"])

    # ---- one table of wells: provincial lists + producing wells missing from them
    w = wells.copy()
    w = w.dropna(subset=["uwi"]).drop_duplicates("uwi")
    missing = sorted(set(p["entity_id"].dropna()) - set(w["uwi"]))
    if missing:
        extra = pd.DataFrame({"uwi": missing})
        extra["province"] = p.drop_duplicates("entity_id").set_index("entity_id").loc[missing, "province"].values
        loc = [locate.locate(u) for u in missing]
        extra["lat"], extra["lon"] = [x[0] for x in loc], [x[1] for x in loc]
        extra["loc_precision"] = [x[2] for x in loc]
        extra["status_group"] = "Producing"
        extra["status_text"] = "Reporting production (not on the provincial well list)"
        oilgas = cur.reindex(missing)
        extra["fluid"] = np.where(oilgas["oil"].fillna(0) * 6 >= oilgas["gas"].fillna(0), "Oil", "Gas")
        for c in WELL_COLS:
            if c not in extra:
                extra[c] = pd.NA
        w = pd.concat([w, extra[WELL_COLS]], ignore_index=True)
    for c in ("lat", "lon", "bh_lat", "bh_lon", "total_depth_m"):
        w[c] = pd.to_numeric(w[c], errors="coerce").astype(float)
    w = w.dropna(subset=["lat", "lon"])
    w["licensee"] = w["licensee"].fillna(w["uwi"].map(prod_op))
    w["sym"] = [symbol(g, f, u in produced, t) for g, f, u, t in zip(w["status_group"], w["fluid"], w["uwi"], w["status_text"])]
    w["boe"] = w["uwi"].map(cur_boe).fillna(0)
    w["key"] = w["uwi"].map(shard_key)
    w["disp"] = w["uwi"].map(display_uwi)

    # ---- grid calibration: per-township offset between the survey formula and surveyed AER surface locations
    offsets, check = grid_offsets(w)
    (out / "grid_offsets.json").write_text(json.dumps(offsets, separators=(",", ":")))
    formula = w["loc_precision"].astype(str).str.startswith("dls")
    if offsets and formula.any():
        tk = w.loc[formula, "uwi"].map(lambda u: (shard_key(u) or "")).map(offsets.get)
        has = tk.notna()
        idx = tk[has].index
        w.loc[idx, "lat"] = w.loc[idx, "lat"] + [o[0] for o in tk[has]]
        w.loc[idx, "lon"] = w.loc[idx, "lon"] + [o[1] for o in tk[has]]

    # ---- operators: merge spellings that differ only in case or suffix (Tourmaline Oil Corp. / TOURMALINE OIL CORP.)
    from .analytics import nice_name, op_key
    raw = w["licensee"].fillna("Unknown").astype(str).str.strip()
    keys = raw.map(lambda x: op_key(x) or x.upper())
    pretty = (pd.DataFrame({"k": keys, "r": raw.map(nice_name)}).groupby("k")["r"]
              .agg(lambda s: s[~s.str.isupper()].mode().iloc[0] if (~s.str.isupper()).any() else s.mode().iloc[0]))
    w["licensee"] = keys.map(pretty)
    ops = (w.assign(n=w["licensee"].fillna("Unknown").astype(str).str.strip())
             .groupby("n").agg(wells=("uwi", "size"), producing=("boe", lambda s: int((s > 0).sum())),
                               s=("lat", "min"), n_=("lat", "max"), wst=("lon", "min"), e=("lon", "max"),
                               boe=("boe", "sum"))
             .sort_values("wells", ascending=False).reset_index())
    op_index = {name: i for i, name in enumerate(ops["n"])}
    w["o"] = w["licensee"].fillna("Unknown").astype(str).str.strip().map(op_index)
    (out / "operators.json").write_text(json.dumps([
        {"n": r.n, "w": int(r.wells), "p": int(r.producing), "boe": round(float(r.boe)),
         "b": [round(r.wst, 4), round(r.s, 4), round(r.e, 4), round(r.n_, 4)]} for r in ops.itertuples()],
        separators=(",", ":")))

    # ---- tile features
    # Zoomed out, draw light "dots" (symbol only); from zoom 9 the "wells" layer carries UWI, operator and rate.
    with open(work / "wells.geojsonl", "w") as f, open(work / "dots.geojsonl", "w") as g:
        for r in w[["lon", "lat", "uwi", "sym", "o", "boe"]].itertuples(index=False):
            geom = {"type": "Point", "coordinates": [round(r.lon, 5), round(r.lat, 5)]}
            f.write(json.dumps({"type": "Feature", "tippecanoe": {"minzoom": 9}, "geometry": geom,
                                "properties": {"u": r.uwi, "s": r.sym, "o": int(r.o), "b": round(float(r.boe), 1)}},
                               separators=(",", ":")) + "\n")
            g.write(json.dumps({"type": "Feature", "tippecanoe": {"maxzoom": 8}, "geometry": geom,
                                "properties": {"s": r.sym, "o": int(r.o)}}, separators=(",", ":")) + "\n")
    hz = w.dropna(subset=["bh_lat", "bh_lon"])
    dist = np.hypot((hz["bh_lat"] - hz["lat"]) * 111.2, (hz["bh_lon"] - hz["lon"]) * 111.32 * np.cos(np.radians(hz["lat"])))
    hz = hz[(dist > 0.3) & (dist < 8)]
    with open(work / "laterals.geojsonl", "w") as f:
        for r in hz[["lon", "lat", "bh_lon", "bh_lat", "uwi", "sym"]].itertuples(index=False):
            f.write(json.dumps({"type": "Feature", "tippecanoe": {"minzoom": 9}, "geometry": {"type": "LineString", "coordinates": [
                [round(r.lon, 6), round(r.lat, 6)], [round(r.bh_lon, 6), round(r.bh_lat, 6)]]},
                "properties": {"u": r.uwi, "s": r.sym}}, separators=(",", ":")) + "\n")

    # ---- township shards: full record + production history
    series = defaultdict(dict)
    if len(p):
        T = len(months)
        for uwi, g in p.groupby("entity_id", sort=False):
            arr = np.zeros((3, T), dtype="float32")
            arr[0, g["mi"].values] = g["oil"].values
            arr[1, g["mi"].values] = g["gas"].values
            arr[2, g["mi"].values] = g["wat"].values
            series[uwi] = [[(round(float(x), 1) if x < 100 else int(round(x))) for x in row] if row.any() else None
                           for row in arr]
    fields = ["province", "well_name", "licence", "licensee", "status_text", "status_group", "status_date", "fluid",
              "field", "formation", "spud_date", "total_depth_m", "horizontal", "lat", "lon", "loc_precision",
              "bh_lat", "bh_lon", "sym", "boe"]
    short = ["p", "n", "li", "lc", "st", "sg", "sd", "fl", "fd", "fm", "sp", "td", "hz", "y", "x", "lp", "by", "bx", "s", "b"]
    n_shards = 0
    for key, g in w.dropna(subset=["key"]).groupby("key"):
        recs = {}
        for r in g[["uwi", "disp"] + fields].itertuples(index=False):
            d = {k: _clean(v) for k, v in zip(["u", "d"] + short, r)}
            d = {k: v for k, v in d.items() if v is not None and v != "" and v is not False}
            if "td" in d:
                d["td"] = round(d["td"])
            if r.uwi in series:
                d["pr"] = series[r.uwi]
            recs[r.uwi] = d
        (out / "twp" / f"{key}.json").write_text(json.dumps({"months": mlabels, "wells": recs}, separators=(",", ":")))
        n_shards += 1

    # ---- licence index
    lic = defaultdict(lambda: defaultdict(list))
    for li, prov, u in w.dropna(subset=["licence"])[["licence", "province", "uwi"]].itertuples(index=False):
        li = str(li).strip().upper()
        if li:
            lic[li[-2:].rjust(2, "0")][li].append([prov, u])
    for sh, d in lic.items():
        (out / "lic" / f"{sh}.json").write_text(json.dumps(d, separators=(",", ":")))

    counts = {"grid_check": check, "wells": int(len(w)), "producing": int((w["boe"] > 0).sum()), "laterals": int(len(hz)),
              "operators": int(len(ops)), "shards": n_shards, "not_on_lists": len(missing),
              "by_province": {k: int(v) for k, v in w["province"].value_counts().items()},
              "by_symbol": {k: int(v) for k, v in w["sym"].value_counts().items()}}
    meta = {"generated": pd.Timestamp.now(tz="UTC").strftime("%Y-%m-%d %H:%M UTC"),
            "months": [mlabels[0], mlabels[-1]] if mlabels else None,
            "latest": {k: pd.Timestamp(v).strftime("%Y-%m") for k, v in latest.items()},
            "counts": counts, "symbols": SYMBOLS, "sources": sources}
    (out / "meta.json").write_text(json.dumps(meta, separators=(",", ":")))
    return meta
