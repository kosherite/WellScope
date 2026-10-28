"""Saskatchewan: Petrinex Saskatchewan public data (well infrastructure + volumes).

Column names below were confirmed from the live Well Infrastructure download (probe run, Oct 2026).
The province's own well and production bundles are paid, so this uses the free Petrinex extracts.
Coordinates are not published there; wells are placed from their DLS location (approximate).
"""
from __future__ import annotations

from pathlib import Path

import pandas as pd

from ..schema import clean_str, finish_wells
from . import petrinex


def _col(df: pd.DataFrame, name: str):
    return df[name] if name in df.columns else pd.NA


def wells(cache: Path) -> pd.DataFrame:
    df = petrinex.infra("SK", "Well Infrastructure", cache)
    if "WellID" not in df.columns:
        raise KeyError(f"SK Well Infrastructure has no WellID column; columns are {list(df.columns)}")
    mode, typ = clean_str(_col(df, "WellStatusMode")), clean_str(_col(df, "WellStatusType"))
    parts = ["WellLocationException", "WellLegalSubdivision", "WellSection", "WellTownship", "WellRange", "WellMeridian",
             "WellEventSequence"]
    uwi = df["WellID"]
    if all(c in df.columns for c in parts):
        n = {c: pd.to_numeric(df[c], errors="coerce") for c in parts[1:]}
        le = df["WellLocationException"].astype(str).str.strip().str[-2:].str.zfill(2)
        built = (le + "/" + n["WellLegalSubdivision"].astype("Int64").astype(str).str.zfill(2) + "-"
                 + n["WellSection"].astype("Int64").astype(str).str.zfill(2) + "-"
                 + n["WellTownship"].astype("Int64").astype(str).str.zfill(3) + "-"
                 + n["WellRange"].astype("Int64").astype(str).str.zfill(2) + "W"
                 + n["WellMeridian"].astype("Int64").astype(str) + "/"
                 + n["WellEventSequence"].astype("Int64").astype(str).str[-1:])
        ok = n["WellSection"].notna() & n["WellTownship"].notna() & n["WellRange"].notna()
        uwi = built.where(ok, df["WellID"])
    out = pd.DataFrame({
        "uwi": uwi,
        "well_name": clean_str(_col(df, "WellName")),
        "licensee": clean_str(_col(df, "LicenseeName")),
        "status": mode.where(mode.notna(), typ),
        "status_date": _col(df, "WellStatusDate"),
        "fluid": clean_str(_col(df, "WellStatusFluid")),
        "field": clean_str(_col(df, "FieldName")),
        "formation": clean_str(_col(df, "PoolDepositName")),
        "spud_date": _col(df, "SpudDate"),
        "total_depth_m": _col(df, "FinalTotalDepth"),
        "horizontal": clean_str(_col(df, "HorizontalDrill")).str.upper().isin(["Y", "YES", "TRUE"]).fillna(False),
    })
    return finish_wells(out, "SK")


def production(cache: Path, months: list[str]) -> pd.DataFrame:
    return petrinex.production("SK", months, cache)
