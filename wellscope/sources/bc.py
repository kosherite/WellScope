"""British Columbia: BC Energy Regulator (BCER) open downloads.

* ``well_index.csv``: every well authorization, with UWI, operator, status, surface location.
* ``prod_csv.zip``: monthly production for all wells in B.C., reported by zone (summed here per UWI).

The BCER does not publish a layout for these CSVs on its data page, so columns are matched by alias.
"""
from __future__ import annotations

from pathlib import Path

import pandas as pd

from .. import fetch
from ..config import SOURCES
from ..schema import clean_str, finish_production, finish_wells


def _csv_from(path: Path, hint: str | None = None) -> pd.DataFrame:
    return fetch.read_table(fetch.unzip_bytes(path.read_bytes(), hint))


def wells(cache: Path) -> pd.DataFrame:
    df = _csv_from(fetch.download(SOURCES["BC"]["well_index"], cache / "BC" / "well_index.csv"))
    p = lambda *a, req=False: fetch.pick(df, *a, required=req)  # noqa: E731
    col = lambda *a: df[p(*a)] if p(*a) else pd.NA  # noqa: E731
    uwi = p("UWI", "Well UWI", "Surface UWI", req=True)
    lat, lon = p("Surf Lat", "Surface Latitude", "Latitude", "Lat"), p("Surf Long", "Surface Longitude", "Longitude", "Long")
    out = pd.DataFrame({
        "uwi": df[uwi],
        "well_name": clean_str(col("Well Name", "Name")),
        "licensee": clean_str(col("Operator", "Oper Abbrev", "Operator Name", "Company")),
        "status": clean_str(col("Current Status", "Well Status", "Status")),
        "status_date": col("Status Date", "Current Status Date"),
        "fluid": clean_str(col("Fluid", "Well Type", "Type")),
        "field": clean_str(col("Field", "Field Name")),
        "formation": clean_str(col("Formation", "Zone", "Pool")),
        "spud_date": col("Spud Date", "Spud"),
        "total_depth_m": col("Total Depth", "TD", "Depth"),
        "horizontal": clean_str(col("Bh Profile", "Profile", "Well Profile", "Bottom Hole Profile")).str.upper().str.startswith("H")
        if p("Bh Profile", "Profile", "Well Profile", "Bottom Hole Profile") else False,
        "lat": df[lat] if lat else pd.NA,
        "lon": df[lon] if lon else pd.NA,
    })
    # BC longitudes are sometimes published as positive degrees west
    lonv = pd.to_numeric(out["lon"], errors="coerce")
    out["lon"] = lonv.where(lonv < 0, -lonv)
    return finish_wells(out, "BC")


def production(cache: Path, months: list[str]) -> pd.DataFrame:
    df = _csv_from(fetch.download(SOURCES["BC"]["production"], cache / "BC" / "prod_csv.zip"), ".csv")
    p = lambda *a, req=False: fetch.pick(df, *a, required=req)  # noqa: E731
    uwi = p("UWI", "Well UWI", req=True)
    per = p("Prod Period", "Production Period", "Period", "Prod Date", "Date", "Month")
    if per:
        month = pd.to_datetime(df[per].astype(str).str.replace(r"[^0-9]", "", regex=True).str[:6], format="%Y%m", errors="coerce")
    else:
        y, m = p("Year", "Prod Year", req=True), p("Month", "Prod Month", req=True)
        month = pd.to_datetime(df[y].astype(str) + "-" + df[m].astype(str).str.zfill(2), format="%Y-%m", errors="coerce")
    num = lambda *a: pd.to_numeric(df[p(*a)], errors="coerce") if p(*a) else 0.0  # noqa: E731
    days = num("Prod Days", "Production Days", "Days On")
    out = pd.DataFrame({
        "entity_id": df[uwi], "entity_type": "well", "month": month,
        "operator": df[p("Operator", "Oper Abbrev", "Operator Name")] if p("Operator", "Oper Abbrev", "Operator Name") else pd.NA,
        "facility_id": pd.NA,
        "oil_m3": num("Oil Prod Vol (m3)", "Oil (m3)", "Oil Volume", "Oil"),
        "gas_e3m3": num("Gas Prod Vol (e3m3)", "Gas (e3m3)", "Gas Volume", "Gas"),
        "cond_m3": num("Cond Prod Vol (m3)", "Condensate (m3)", "Cond Volume", "Condensate", "Cond"),
        "water_m3": num("Water Prod Vol (m3)", "Water (m3)", "Water Volume", "Water"),
        "hours": days * 24 if not isinstance(days, float) else num("Hours", "Prod Hours"),
    })
    keep = sorted(out["month"].dropna().unique())[-len(months):]
    return finish_production(out[out["month"].isin(keep)], "BC")
