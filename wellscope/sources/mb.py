"""Manitoba: Petroleum Branch well monthly production workbooks + weekly UWI list.

Production comes as Excel workbooks inside multi-year zips. Volumes for GAS/GSD are in 1000 m3 and all
other fluids in m3 (per the Branch's reports page). Locations come from the DLS UWI (approximate).
"""
from __future__ import annotations

import io
import zipfile
from pathlib import Path

import pandas as pd

from .. import fetch
from ..config import SOURCES
from ..schema import clean_str, finish_production, finish_wells


def wells(cache: Path) -> pd.DataFrame:
    raw = fetch.download(SOURCES["MB"]["uwi_list"], cache / "MB" / "uwi_weekly.xlsx")
    df = pd.read_excel(raw, dtype=str)
    p = lambda *a, req=False: fetch.pick(df, *a, required=req)  # noqa: E731
    col = lambda *a: df[p(*a)] if p(*a) else pd.NA  # noqa: E731
    out = pd.DataFrame({
        "uwi": df[p("UWI", "Unique Well Identifier", req=True)],
        "well_name": clean_str(col("Well Name", "Name")),
        "licensee": clean_str(col("Licensee", "Company", "Operator")),
        "status": clean_str(col("Status", "Well Status", "Current Status")),
        "status_date": col("Status Date"),
        "fluid": clean_str(col("Fluid", "Well Type")),
        "field": clean_str(col("Field", "Field Name")),
        "formation": clean_str(col("Formation", "Pool", "Zone")),
        "spud_date": col("Spud Date", "Spud"),
        "total_depth_m": col("Total Depth", "TD"),
        "horizontal": clean_str(col("Hz", "Horizontal", "Well Profile")).str.upper().str.startswith(("Y", "H"))
        if p("Hz", "Horizontal", "Well Profile") else False,
        "lat": col("Latitude", "Surface Latitude", "Lat"),
        "lon": col("Longitude", "Surface Longitude", "Long"),
    })
    return finish_wells(out, "MB")


def _sheets(zpath: Path):
    with zipfile.ZipFile(zpath) as z:
        for n in z.namelist():
            if n.lower().endswith((".xlsx", ".xls")):
                for name, df in pd.read_excel(io.BytesIO(z.read(n)), sheet_name=None, dtype=str).items():
                    yield f"{n}:{name}", df


def _standardize(df: pd.DataFrame) -> pd.DataFrame:
    p = lambda *a, req=False: fetch.pick(df, *a, required=req)  # noqa: E731
    uwi = p("UWI", "Well", req=True)
    per = p("Production Date", "Prod Date", "Period", "Date", "Month")
    if per:
        month = pd.to_datetime(df[per], errors="coerce")
    else:
        month = pd.to_datetime(df[p("Year", req=True)].astype(str) + "-" + df[p("Month", req=True)].astype(str).str.zfill(2),
                               format="%Y-%m", errors="coerce")
    fluid, vol = p("Fluid", "Fluid Type", "Product"), p("Volume", "Vol")
    if fluid and vol:   # long format: one row per fluid
        f = df[fluid].astype(str).str.upper().str.strip()
        v = pd.to_numeric(df[vol], errors="coerce").fillna(0)
        out = pd.DataFrame({"entity_id": df[uwi], "month": month,
                            "oil_m3": v.where(f.eq("OIL"), 0), "water_m3": v.where(f.str.startswith("WAT"), 0),
                            "gas_e3m3": v.where(f.isin(["GAS", "GSD"]), 0), "cond_m3": v.where(f.str.startswith("COND"), 0)})
    else:
        num = lambda *a: pd.to_numeric(df[p(*a)], errors="coerce") if p(*a) else 0.0  # noqa: E731
        out = pd.DataFrame({"entity_id": df[uwi], "month": month, "oil_m3": num("Oil"), "water_m3": num("Water"),
                            "gas_e3m3": num("Gas"), "cond_m3": num("Condensate", "Cond")})
    hrs = p("Hours", "Prod Hours", "Hours On")
    out["hours"] = pd.to_numeric(df[hrs], errors="coerce") if hrs else 0.0
    out["entity_type"] = "well"
    return out


def production(cache: Path, months: list[str]) -> pd.DataFrame:
    parts = []
    for i, url in enumerate(SOURCES["MB"]["production"]):
        zpath = fetch.download(url, cache / "MB" / f"wmp_{i}.zip")
        for label, sheet in _sheets(zpath):
            try:
                parts.append(_standardize(sheet))
            except KeyError as e:
                print(f"  MB sheet {label} skipped: {e}")
    if not parts:
        raise RuntimeError("No Manitoba production sheets could be read")
    df = pd.concat(parts, ignore_index=True)
    keep = sorted(df["month"].dropna().unique())[-len(months):]
    return finish_production(df[df["month"].isin(keep)], "MB")
