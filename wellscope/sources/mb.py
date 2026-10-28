"""Manitoba: Petroleum Branch well monthly production workbooks + weekly UWI list.

Layouts confirmed from the live files (probe run, Oct 2026):

* Production: one row per well, fluid and year, months as columns
  ``UWI, NAME (licensee), FLUID CODE, YEAR, JAN ... DEC, DEVIATION, POOL NAME``.
  GAS/GSD volumes are 1000 m3; other fluids m3.
* UWI list: ``UWI, COMPANY, CURRENT STATUS, WELL STATUS DATE, DEVIATION, LOCATION, FIELD CODE, POOL CODE``.
UWIs are written with dots (``100.14-14-009-29W1.00``). Locations come from the DLS UWI.
"""
from __future__ import annotations

import io
import zipfile
from pathlib import Path

import pandas as pd

from .. import fetch
from ..config import SOURCES
from ..schema import clean_str, finish_production, finish_wells

MONTHS = ["JAN", "FEB", "MAR", "APR", "MAY", "JUN", "JUL", "AUG", "SEP", "OCT", "NOV", "DEC"]


def _up(df: pd.DataFrame) -> pd.DataFrame:
    df = df.copy()
    df.columns = [str(c).strip().upper() for c in df.columns]
    return df


def _col(df, name):
    return df[name] if name in df.columns else pd.NA


def wells(cache: Path) -> pd.DataFrame:
    df = _up(pd.read_excel(fetch.download(SOURCES["MB"]["uwi_list"], cache / "MB" / "uwi_weekly.xlsx"), dtype=str))
    if "UWI" not in df.columns:
        raise KeyError(f"MB UWI list has no UWI column; columns are {list(df.columns)}")
    status = clean_str(_col(df, "UWI STATUS"))
    status = status.where(status.notna(), clean_str(_col(df, "CURRENT STATUS")))
    out = pd.DataFrame({
        "uwi": df["UWI"].astype(str).str.replace(".", "/", regex=False),
        "well_name": clean_str(_col(df, "NAME")),
        "licensee": clean_str(_col(df, "COMPANY")),
        "status": status,
        "status_date": pd.to_datetime(_col(df, "UWI STATUS DATE"), errors="coerce", format="mixed"),
        "fluid": pd.NA,
        "field": clean_str(_col(df, "FIELD CODE")),
        "formation": clean_str(_col(df, "POOL CODE")),
        "horizontal": clean_str(_col(df, "DEVIATION")).str.upper().str.startswith("H").fillna(False),
    })
    return finish_wells(out, "MB")


def _sheets(zpath: Path):
    with zipfile.ZipFile(zpath) as z:
        for n in z.namelist():
            if n.lower().endswith((".xlsx", ".xls")):
                for name, df in pd.read_excel(io.BytesIO(z.read(n)), sheet_name=None, dtype=str).items():
                    yield f"{n}:{name}", df


def _standardize(df: pd.DataFrame) -> pd.DataFrame:
    df = _up(df)
    need = {"UWI", "FLUID CODE", "YEAR"} | set(MONTHS)
    if not need <= set(df.columns):
        raise KeyError(f"expected {sorted(need - set(df.columns))}; columns are {list(df.columns)}")
    long = df.melt(id_vars=[c for c in df.columns if c not in MONTHS], value_vars=MONTHS, var_name="MON", value_name="VOL")
    long["VOL"] = pd.to_numeric(long["VOL"], errors="coerce").fillna(0)
    long = long[long["VOL"] != 0]
    mnum = long["MON"].map({m: i + 1 for i, m in enumerate(MONTHS)})
    long["month"] = pd.to_datetime(long["YEAR"].astype(str).str[:4] + "-" + mnum.astype(str).str.zfill(2), format="%Y-%m", errors="coerce")
    f = long["FLUID CODE"].astype(str).str.upper().str.strip()
    v = long["VOL"]
    out = pd.DataFrame({
        "entity_id": long["UWI"].astype(str).str.replace(".", "/", regex=False), "entity_type": "well", "month": long["month"],
        "operator": _col(long, "NAME"), "facility_id": pd.NA, "location": pd.NA,
        "oil_m3": v.where(f.eq("OIL"), 0), "water_m3": v.where(f.str.startswith("WAT"), 0),
        "gas_e3m3": v.where(f.isin(["GAS", "GSD"]), 0), "cond_m3": v.where(f.str.startswith("CON"), 0), "hours": 0.0,
    })
    return out


def production(cache: Path, months: list[str]) -> pd.DataFrame:
    parts, problems = [], []
    for i, url in enumerate(SOURCES["MB"]["production"]):
        zpath = fetch.download(url, cache / "MB" / f"wmp_{i}.zip")
        for label, sheet in _sheets(zpath):
            try:
                parts.append(_standardize(sheet))
            except KeyError as e:
                problems.append(f"{label}: {e}")
    if not parts:
        raise RuntimeError("No Manitoba production sheets could be read: " + "; ".join(problems[:3]))
    df = pd.concat(parts, ignore_index=True)
    keep = sorted(df["month"].dropna().unique())[-len(months):]
    return finish_production(df[df["month"].isin(keep)], "MB")
