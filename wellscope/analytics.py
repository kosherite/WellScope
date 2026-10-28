"""Turn the unified wells + production tables into the metrics an E&P analyst screens on.

Conventions (see the RBC primer "Energy Made Simple"): oil and condensate in bbl/d, gas in mcf/d, boe at
6 mcf = 1 boe, rates per calendar day. P10/P50/P90 follow the reserves convention: P10 is the high case
(10% of wells do better), P90 the low case.
"""
from __future__ import annotations

import json
import math
import re
from pathlib import Path

import numpy as np
import pandas as pd

from . import locate, model
from .config import DEFAULTS, E3M3_TO_MCF, M3_TO_BBL, MCF_PER_BOE, PRICE_DECK

SUFFIX = re.compile(r"\b(LTD|LIMITED|INC|INCORPORATED|CORP|CORPORATION|ULC|CO|COMPANY|LP|PARTNERSHIP|THE)\b\.?")


def op_key(name) -> str | None:
    if name is None or (isinstance(name, float) and math.isnan(name)) or pd.isna(name):
        return None
    n = str(name).upper().replace("&", " AND ")
    n = re.sub(r"[^A-Z0-9 ]", " ", n)
    n = SUFFIX.sub(" ", n)
    n = re.sub(r"\s+", " ", n).strip()
    return n or None


def slug(s: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", str(s).lower()).strip("-")[:60] or "x"


def nice_name(name) -> str:
    if name is None or pd.isna(name):
        return "Unknown"
    s = str(name).strip()
    if s.isupper():
        keep = {"II", "III", "IV", "ULC", "LP", "AB", "BC", "SK", "MB", "USA", "NGL", "CNRL"}
        s = " ".join(w if w.strip(".,") in keep or (len(w) <= 3 and not w.strip(".,").isalpha()) else w.capitalize()
                     for w in s.split())
    return s


# ------------------------------------------------------------------ preparation
def prepare(wells: pd.DataFrame, prod: pd.DataFrame):
    """Return (entities, matrices, months, latest index per province)."""
    prod = prod.copy()
    days = prod["month"].dt.days_in_month.astype("float32")
    prod["oil_bpd"] = (prod["oil_m3"] + prod["cond_m3"]) * M3_TO_BBL / days
    prod["gas_mcfd"] = prod["gas_e3m3"] * E3M3_TO_MCF / days
    prod["water_bpd"] = prod["water_m3"] * M3_TO_BBL / days
    prod["boe_d"] = prod["oil_bpd"] + prod["gas_mcfd"] / MCF_PER_BOE

    # Each province reports with its own lag; drop trailing months that are clearly incomplete.
    latest = {}
    for prov, g in prod.groupby("province"):
        tot = g.groupby("month")["boe_d"].sum().sort_index()
        last = tot.index[-1]
        for mth in reversed(tot.index):
            ref = tot[tot.index < mth].tail(6)
            if len(ref) == 0 or tot[mth] >= 0.8 * ref.median():
                last = mth
                break
        latest[prov] = last
    prod = prod[prod.apply(lambda r: r["month"] <= latest[r["province"]], axis=1)] if len(prod) < 50_000 else \
        prod[prod["month"] <= prod["province"].map(latest)]

    months = sorted(prod["month"].unique())
    midx = {m: i for i, m in enumerate(months)}
    prod["mi"] = prod["month"].map(midx)

    key = ["entity_id", "entity_type", "province"]
    prod = prod.sort_values("month")
    ent = prod.groupby(key, as_index=False, observed=True).agg(
        operator=("operator", "last"), facility_id=("facility_id", "last"), location=("location", "last"))
    ent["eid"] = np.arange(len(ent))
    prod = prod.merge(ent[key + ["eid"]], on=key)

    n, T = len(ent), len(months)
    mats = {}
    for c in ("boe_d", "oil_bpd", "gas_mcfd", "water_bpd"):
        m = np.zeros((n, T), dtype="float32")
        np.add.at(m, (prod["eid"].to_numpy(), prod["mi"].to_numpy()), prod[c].to_numpy(dtype="float32"))
        mats[c] = m
    # months after a province's latest month are unknown, not zero
    last_i = ent["province"].map({p: midx[m] for p, m in latest.items()}).to_numpy()
    ent["last_i"] = last_i
    unknown = np.arange(T)[None, :] > last_i[:, None]
    for m in mats.values():
        m[unknown] = np.nan

    pos = mats["boe_d"] > 0
    ent["onset"] = np.where(pos.any(1), pos.argmax(1), -1)
    ent["first_month"] = [months[i].strftime("%Y-%m") if i >= 0 else None for i in ent["onset"]]

    # attributes from the well lists
    w = wells.set_index("uwi")
    is_w = ent["entity_type"].eq("well")
    for c in ("well_name", "licensee", "status_group", "fluid", "formation", "horizontal", "lat", "lon",
              "loc_precision", "total_depth_m", "spud_date"):
        ent[c] = pd.NA
        ent.loc[is_w, c] = ent.loc[is_w, "entity_id"].map(w[c]) if c in w else pd.NA
    ent["lat"] = pd.to_numeric(ent["lat"], errors="coerce").astype(float)
    ent["lon"] = pd.to_numeric(ent["lon"], errors="coerce").astype(float)
    ent["loc_precision"] = ent["loc_precision"].astype("object")
    need = ent["lat"].isna()
    src = ent["entity_id"].where(is_w, ent["location"])
    loc = src[need].map(locate.locate)
    ent.loc[need, "lat"] = np.array([np.nan if x[0] is None else x[0] for x in loc], dtype=float)
    ent.loc[need, "lon"] = np.array([np.nan if x[1] is None else x[1] for x in loc], dtype=float)
    ent.loc[need, "loc_precision"] = [x[2] for x in loc]
    ent["lat"] = pd.to_numeric(ent["lat"], errors="coerce")
    ent["lon"] = pd.to_numeric(ent["lon"], errors="coerce")
    ent["area"] = [locate.area_key(a, b) for a, b in zip(ent["lat"], ent["lon"])]
    ent["op_name"] = ent["operator"].fillna(ent["licensee"]).map(nice_name)
    ent["op_key"] = ent["operator"].fillna(ent["licensee"]).map(op_key)
    ent["horizontal"] = ent["horizontal"].fillna(False).astype(bool)

    # current rates: average of each province's last three reported months
    cur = {}
    for c, m in mats.items():
        vals = np.full(n, np.nan, dtype="float32")
        for li in np.unique(last_i):
            rows = last_i == li
            vals[rows] = np.nanmean(m[rows, max(0, li - 2): li + 1], axis=1)
        cur[c] = np.nan_to_num(vals)
        ent["cur_" + c] = cur[c]
    return ent, mats, months, latest


# ------------------------------------------------------------------ group metrics
def _quant_curve(series_rows: np.ndarray, horizon: int, min_n: int):
    """P10/P50/P90 by month-on-production from rows already aligned to their first month."""
    out = {"p10": [], "p50": [], "p90": [], "n": []}
    for k in range(horizon):
        col = series_rows[:, k]
        col = col[~np.isnan(col)]
        if len(col) < min_n:
            break
        out["p10"].append(round(float(np.percentile(col, 90)), 1))
        out["p50"].append(round(float(np.percentile(col, 50)), 1))
        out["p90"].append(round(float(np.percentile(col, 10)), 1))
        out["n"].append(int(len(col)))
    return out if out["p50"] else None


def aligned(mat: np.ndarray, rows: np.ndarray, onset: np.ndarray, horizon: int) -> np.ndarray:
    a = np.full((len(rows), horizon), np.nan, dtype="float32")
    for j, (r, o) in enumerate(zip(rows, onset)):
        seg = mat[r, o:o + horizon]
        a[j, :len(seg)] = seg
    return a


def group_metrics(idx: np.ndarray, ent: pd.DataFrame, mats: dict, months: list, horizon: int, min_n: int,
                  detail: bool) -> dict:
    """Metrics for one group of entities (row indices into ent and the matrices)."""
    e = ent.iloc[idx]
    boe = mats["boe_d"][idx]
    last_i = int(e["last_i"].max())
    hist = np.nansum(boe, axis=0)
    cur_boe = float(e["cur_boe_d"].sum())
    cur_oil = float(e["cur_oil_bpd"].sum())
    cur_gas = float(e["cur_gas_mcfd"].sum())
    cur_wat = float(e["cur_water_bpd"].sum())
    producing = int((e["cur_boe_d"] > 0).sum())
    onset = e["onset"].to_numpy()
    new_mask = onset >= 3
    is_well = e["entity_type"].eq("well").to_numpy()
    new12 = int(((onset >= last_i - 11) & new_mask).sum())

    # base decline: entities online for 15+ months; last 3 months vs the same months a year earlier
    base_rows = idx[(onset >= 0) & (onset <= last_i - 15)]
    decline = None
    if len(base_rows) and last_i >= 14:
        now = np.nansum(mats["boe_d"][base_rows, last_i - 2:last_i + 1])
        prev = np.nansum(mats["boe_d"][base_rows, last_i - 14:last_i - 11])
        if prev > 0:
            decline = round(float(1 - now / prev) * 100, 1)

    res = {
        "boe": round(cur_boe, 1), "oil": round(cur_oil, 1), "gas": round(cur_gas, 1),
        "oil_pct": round(cur_oil / cur_boe * 100, 1) if cur_boe > 0 else None,
        "wcut": round(cur_wat / (cur_wat + cur_oil) * 100, 1) if cur_wat + cur_oil > 0 else None,
        "gor": round(cur_gas / cur_oil * 1000) if cur_oil > 1 else None,           # scf/bbl
        "producing": producing, "new12": new12, "decline": decline,
    }
    if not detail:
        return res

    T = len(months)
    res["history"] = {
        "boe": [round(float(x), 1) for x in hist[: last_i + 1]],
        "oil": [round(float(x), 1) for x in np.nansum(mats["oil_bpd"][idx], axis=0)[: last_i + 1]],
        "gas": [round(float(x), 1) for x in np.nansum(mats["gas_mcfd"][idx], axis=0)[: last_i + 1]],
        "wells": [int(x) for x in (np.nan_to_num(boe) > 0).sum(0)[: last_i + 1]],
    }
    # new-well type curve and IPs
    # type curves only make sense for single wells, not whole batteries
    tc_mask = new_mask & is_well
    nrows = idx[tc_mask]
    if len(nrows) >= min_n:
        al = aligned(mats["boe_d"], nrows, onset[tc_mask], min(horizon, T))
        res["type_curve"] = _quant_curve(al, min(horizon, T), min_n)
        hz = e["horizontal"].to_numpy()[tc_mask]
        if hz.sum() >= min_n and (~hz).sum() >= min_n:
            res["type_curve_hz"] = _quant_curve(al[hz], min(horizon, T), min_n)
            res["type_curve_vt"] = _quant_curve(al[~hz], min(horizon, T), min_n)
        ip90 = np.nanmean(al[:, :3], axis=1)
        ip90 = ip90[~np.isnan(ip90)]
        res["ip90"] = round(float(np.median(ip90)), 1) if len(ip90) else None
        full12 = al[~np.isnan(al[:, 11])] if al.shape[1] >= 12 else np.empty((0, 12))
        res["ip365"] = round(float(np.median(full12[:, :12].mean(1))), 1) if len(full12) >= min_n else None
        res["new_by_month"] = [int(((onset == k) & tc_mask).sum()) for k in range(last_i + 1)]
    # PDP: wells online 12+ months, aggregate decline fit, valued in the browser
    pdp_rows = idx[(onset >= 0) & (onset <= last_i - 12)]
    if len(pdp_rows):
        series = np.nansum(mats["boe_d"][pdp_rows, : last_i + 1], axis=0)
        oil = np.nansum(mats["oil_bpd"][pdp_rows, last_i - 2: last_i + 1])
        tot = np.nansum(mats["boe_d"][pdp_rows, last_i - 2: last_i + 1])
        fit = model.fit_range(series[-24:]) if series[-1] > 0 else None
        if fit:
            fit["oil_frac"] = round(float(oil / tot), 3) if tot > 0 else 0
            fit["wells"] = int(len(pdp_rows))
            fit["hist"] = [round(float(x), 1) for x in series[-24:]]
            res["pdp"] = fit
        bt = model.backtest(series)
        if bt is not None:
            res["backtest"] = round(bt * 100, 1)
    return res


def well_rows(e: pd.DataFrame, mats: dict, limit: int) -> list:
    e = e.sort_values("cur_boe_d", ascending=False).head(limit)
    out = []
    for r in e.itertuples():
        spark = mats["boe_d"][r.Index, max(0, r.last_i - 23): r.last_i + 1]
        out.append({
            "id": r.entity_id, "type": r.entity_type, "name": None if pd.isna(r.well_name) else str(r.well_name),
            "op": r.op_name, "status": None if pd.isna(r.status_group) else r.status_group,
            "fluid": None if pd.isna(r.fluid) else r.fluid, "hz": bool(r.horizontal),
            "form": None if pd.isna(r.formation) else str(r.formation),
            "boe": round(float(r.cur_boe_d), 1), "oil": round(float(r.cur_oil_bpd), 1),
            "gas": round(float(r.cur_gas_mcfd), 1), "first": r.first_month,
            "lat": None if pd.isna(r.lat) else round(float(r.lat), 5),
            "lon": None if pd.isna(r.lon) else round(float(r.lon), 5),
            "prec": None if pd.isna(r.loc_precision) else r.loc_precision,
            "spark": [round(float(x), 1) for x in np.nan_to_num(spark)],
        })
    return out


def liability(wells: pd.DataFrame, by: pd.Series) -> pd.DataFrame:
    w = wells.assign(_k=by)
    inactive = w["status_group"].eq("Inactive")
    cost = DEFAULTS["cleanup_base"] + DEFAULTS["cleanup_per_m"] * w["total_depth_m"].fillna(1500)
    w["_cost"] = np.where(inactive, cost, 0.0)
    g = w.groupby("_k")
    return pd.DataFrame({
        "wells": g.size(),
        "producing_lic": g["status_group"].apply(lambda s: int((s == "Producing").sum())),
        "inactive": g["status_group"].apply(lambda s: int((s == "Inactive").sum())),
        "abandoned": g["status_group"].apply(lambda s: int((s == "Abandoned").sum())),
        "cleanup": g["_cost"].sum().round(0),
    })


def activity(wells: pd.DataFrame, years: int = 12) -> dict:
    if wells.empty or not pd.api.types.is_datetime64_any_dtype(wells["spud_date"]):
        return {"years": [], "by_province": {}, "horizontal_share": []}
    w = wells.dropna(subset=["spud_date"])
    w = w[w["spud_date"].dt.year >= pd.Timestamp.today().year - years]
    y = w["spud_date"].dt.year
    tab = w.groupby([y, "province"]).size().unstack(fill_value=0)
    hz = w[w["horizontal"]].groupby(y).size()
    return {"years": [int(x) for x in tab.index],
            "by_province": {p: [int(v) for v in tab[p]] for p in tab.columns},
            "horizontal_share": [round(float(hz.get(yr, 0) / tab.loc[yr].sum() * 100), 1) for yr in tab.index]}


def location_check(wells: pd.DataFrame) -> dict | None:
    """Distance between surveyed coordinates and the DLS formula, for wells that have both."""
    s = wells[wells["loc_precision"].eq("surveyed")].sample(n=min(20000, (wells["loc_precision"] == "surveyed").sum()),
                                                            random_state=1) if (wells["loc_precision"] == "surveyed").any() else None
    if s is None or s.empty:
        return None
    d = []
    for u, la, lo in zip(s["uwi"], s["lat"], s["lon"]):
        a, b, prec = locate.locate(u)
        if a is None:
            continue
        dy = (a - la) * 111.2
        dx = (b - lo) * 111.32 * math.cos(math.radians(la))
        d.append(math.hypot(dx, dy))
    if not d:
        return None
    return {"n": len(d), "median_km": round(float(np.median(d)), 2), "p90_km": round(float(np.percentile(d, 90)), 2)}


# ------------------------------------------------------------------ publish
def build(wells: pd.DataFrame, prod: pd.DataFrame, out: Path, sources: dict, horizon: int | None = None,
          min_n: int | None = None, cell_well_limit: int = 80, op_well_limit: int = 120) -> dict:
    horizon = horizon or DEFAULTS["type_curve_months"]
    min_n = min_n or DEFAULTS["min_wells_type_curve"]
    out = Path(out)
    (out / "cells").mkdir(parents=True, exist_ok=True)
    (out / "operators").mkdir(parents=True, exist_ok=True)

    ent, mats, months, latest = prepare(wells, prod)
    mlabels = [m.strftime("%Y-%m") for m in months]
    print(f"  {len(ent):,} producing entities, {len(months)} months, latest {dict((k, v.strftime('%Y-%m')) for k, v in latest.items())}")

    wells = wells.copy()
    wells["area"] = [locate.area_key(a, b) for a, b in zip(wells["lat"], wells["lon"])]
    wells["op_key"] = wells["licensee"].map(op_key)
    liab_area = liability(wells, wells["area"])
    liab_op = liability(wells, wells["op_key"])

    def dump(path: Path, obj):
        path.write_text(json.dumps(obj, separators=(",", ":"), allow_nan=False, default=_json_default))

    # ---- areas
    cells = []
    backtests = []
    for area, g in ent.groupby("area"):
        idx = g.index.to_numpy()
        m = group_metrics(idx, ent, mats, months, horizon, min_n, detail=True)
        s, wst, n, e_ = locate.area_bounds(area)
        lb = liab_area.loc[area] if area in liab_area.index else None
        ops = g.groupby("op_name")["cur_boe_d"].sum().sort_values(ascending=False)
        top = [{"op": k, "boe": round(float(v), 1), "share": round(float(v / ops.sum() * 100), 1) if ops.sum() > 0 else 0}
               for k, v in ops.head(8).items() if v > 0]
        dls = locate.parse_dls(g["entity_id"].iloc[0]) or locate.parse_dls(g["location"].dropna().iloc[0] if g["location"].notna().any() else None)
        label = dls.township_key if dls else f"{(s + n) / 2:.2f}N {abs((wst + e_) / 2):.2f}W"
        prov = g["province"].mode().iloc[0]
        summary = {k: m.get(k) for k in ("boe", "oil", "gas", "oil_pct", "wcut", "gor", "producing", "new12", "decline", "ip90")}
        summary.update({"id": area, "label": label, "prov": prov, "b": [round(s, 3), round(wst, 3), round(n, 3), round(e_, 3)],
                        "top": top[0]["op"] if top else None,
                        "inactive": int(lb["inactive"]) if lb is not None else 0,
                        "wells": int(lb["wells"]) if lb is not None else int(len(g))})
        cells.append(summary)
        if "backtest" in m and m["boe"] > 50:
            backtests.append(m["backtest"])
        detail = dict(summary, **{k: v for k, v in m.items() if k not in summary}, months=mlabels[: len(m["history"]["boe"])],
                      operators=top, liability=None if lb is None else {k: float(v) for k, v in lb.items()},
                      wells_list=well_rows(g, mats, cell_well_limit))
        dump(out / "cells" / f"{area}.json", detail)
    # areas with wells but no reported production still matter for liability screening
    have = {c["id"] for c in cells}
    for area, lb in liab_area.iterrows():
        if area is None or area in have or not lb["inactive"]:
            continue
        s, wst, n, e_ = locate.area_bounds(area)
        cells.append({"id": area, "label": f"{(s + n) / 2:.2f}N {abs((wst + e_) / 2):.2f}W", "prov": None,
                      "b": [round(s, 3), round(wst, 3), round(n, 3), round(e_, 3)], "boe": 0, "oil": 0, "gas": 0,
                      "oil_pct": None, "wcut": None, "gor": None, "producing": 0, "new12": 0, "decline": None, "ip90": None,
                      "top": None, "inactive": int(lb["inactive"]), "wells": int(lb["wells"])})
    dump(out / "cells.json", cells)

    # ---- operators
    ops = []
    for k, g in ent.groupby("op_key"):
        if k is None:
            continue
        idx = g.index.to_numpy()
        m = group_metrics(idx, ent, mats, months, horizon, min_n, detail=True)
        name = g["op_name"].mode().iloc[0]
        lb = liab_op.loc[k] if k in liab_op.index else None
        sl = slug(k)
        areas = g.groupby("area")["cur_boe_d"].sum().sort_values(ascending=False)
        prov = g.groupby("province")["cur_boe_d"].sum()
        summary = {k2: m.get(k2) for k2 in ("boe", "oil", "gas", "oil_pct", "wcut", "gor", "producing", "new12", "decline", "ip90")}
        summary.update({"id": sl, "name": name, "pdp": m.get("pdp"),
                        "prov": {p: round(float(v), 1) for p, v in prov.items() if v > 0},
                        "inactive": int(lb["inactive"]) if lb is not None else None,
                        "cleanup": float(lb["cleanup"]) if lb is not None else None,
                        "lic_wells": int(lb["wells"]) if lb is not None else None})
        if summary["boe"] <= 0 and not summary["inactive"]:
            continue
        ops.append(summary)
        detail = dict(summary, **{k2: v for k2, v in m.items() if k2 not in summary}, months=mlabels[: len(m["history"]["boe"])],
                      areas=[{"id": a, "boe": round(float(v), 1)} for a, v in areas.head(40).items() if a and v > 0],
                      liability=None if lb is None else {k2: float(v) for k2, v in lb.items()},
                      wells_list=well_rows(g, mats, op_well_limit))
        dump(out / "operators" / f"{sl}.json", detail)
    ops.sort(key=lambda o: o["boe"] or 0, reverse=True)
    dump(out / "operators.json", ops)

    # ---- basin / provinces
    provinces = {}
    for p, g in ent.groupby("province"):
        m = group_metrics(g.index.to_numpy(), ent, mats, months, horizon, min_n, detail=True)
        wl = wells[wells["province"] == p]
        m["status_counts"] = {k: int(v) for k, v in wl["status_group"].value_counts().items()}
        m["latest"] = latest[p].strftime("%Y-%m")
        m["months"] = mlabels[: len(m["history"]["boe"])]
        m.pop("new_by_month", None)
        provinces[p] = m
    basin = group_metrics(ent.index.to_numpy(), ent, mats, months, horizon, min_n, detail=True)
    basin["months"] = mlabels[: len(basin["history"]["boe"])]
    basin["status_counts"] = {k: int(v) for k, v in wells["status_group"].value_counts().items()}
    basin["wells_total"] = int(len(wells))
    dump(out / "basin.json", {"basin": basin, "provinces": provinces, "activity": activity(wells),
                              "top_operators": ops[:25]})

    bt = np.array(backtests)
    meta = {
        "generated": pd.Timestamp.now(tz="UTC").strftime("%Y-%m-%d %H:%M UTC"),
        "months": [mlabels[0], mlabels[-1]], "latest": {k: v.strftime("%Y-%m") for k, v in latest.items()},
        "counts": {"wells": int(len(wells)), "entities": int(len(ent)), "areas": len(cells), "operators": len(ops),
                   "well_level_share": round(float(ent["entity_type"].eq("well").mean()), 3)},
        "backtest": None if not len(bt) else {"n": int(len(bt)), "median_abs_err": round(float(np.median(np.abs(bt))), 1),
                                              "bias": round(float(np.median(bt)), 1),
                                              "within_15": round(float((np.abs(bt) <= 15).mean() * 100), 1)},
        "location_check": location_check(wells),
        "price_deck": PRICE_DECK, "sources": sources,
        "units": "Rates per calendar day. Oil includes condensate. boe = oil bbl + gas mcf / 6.",
    }
    dump(out / "meta.json", meta)
    return meta


def _json_default(o):
    if isinstance(o, (np.integer,)):
        return int(o)
    if isinstance(o, (np.floating,)):
        return None if not np.isfinite(o) else float(o)
    if isinstance(o, (pd.Timestamp,)):
        return o.strftime("%Y-%m-%d")
    if o is pd.NA or o is None:
        return None
    return str(o)
