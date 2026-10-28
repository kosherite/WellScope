"""Saskatchewan: Petrinex Saskatchewan public data (well infrastructure + volumes).

The Saskatchewan government's own well and production bundles are paid subscriptions, so this uses the
free Petrinex extracts. Well coordinates are not in those extracts, so wells are placed from their DLS
UWI (approximate, flagged as such).
"""
from __future__ import annotations

from pathlib import Path

import pandas as pd

from .. import fetch
from ..schema import clean_str, finish_wells
from . import petrinex


def wells(cache: Path) -> pd.DataFrame:
    df = petrinex.infra("SK", "Well Infrastructure", cache)
    p = lambda *a, req=False: fetch.pick(df, *a, required=req)  # noqa: E731
    uwi = p("Well ID", "WellID", "UWI", "Well Identifier", req=True)
    out = pd.DataFrame({
        "uwi": df[uwi],
        "well_name": clean_str(df[p("Well Name")]) if p("Well Name") else pd.NA,
        "licensee": clean_str(df[p("Licensee Name", "Licensee", "Operator Name")]) if p("Licensee Name", "Licensee", "Operator Name") else pd.NA,
        "status": clean_str(df[p("Well Status", "Status Description", "Status")]) if p("Well Status", "Status Description", "Status") else pd.NA,
        "status_date": df[p("Well Status Date", "Status Date")] if p("Well Status Date", "Status Date") else pd.NA,
        "fluid": clean_str(df[p("Well Fluid", "Fluid")]) if p("Well Fluid", "Fluid") else pd.NA,
        "field": clean_str(df[p("Field Name", "Field")]) if p("Field Name", "Field") else pd.NA,
        "formation": clean_str(df[p("Pool Name", "Horizon", "Pool")]) if p("Pool Name", "Horizon", "Pool") else pd.NA,
        "spud_date": df[p("Spud Date")] if p("Spud Date") else pd.NA,
        "total_depth_m": df[p("Final Total Depth", "Total Depth")] if p("Final Total Depth", "Total Depth") else pd.NA,
        "horizontal": df[p("Horizontal Drill", "Horizontal")].astype("string").str.upper().isin(["Y", "YES", "TRUE"])
        if p("Horizontal Drill", "Horizontal") else False,
    })
    return finish_wells(out, "SK")


def production(cache: Path, months: list[str]) -> pd.DataFrame:
    return petrinex.production("SK", months, cache)
