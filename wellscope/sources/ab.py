"""Alberta: AER ST37 well list (surveyed surface coordinates) + Petrinex Alberta volumes."""
from __future__ import annotations

import zipfile
from pathlib import Path

import pandas as pd

from .. import fetch
from ..config import SOURCES
from ..schema import clean_str, finish_wells
from . import petrinex


def _find(z: zipfile.ZipFile, key: str) -> str:
    hits = [n for n in z.namelist() if key in n.lower().replace(" ", "") and n.lower().endswith((".xlsx", ".csv"))]
    if not hits:
        raise FileNotFoundError(f"No file matching '{key}' in ST37 package. Files: {z.namelist()}")
    return hits[0]


def _read(z: zipfile.ZipFile, name: str, cols: list[str]) -> pd.DataFrame:
    with z.open(name) as f:
        if name.lower().endswith(".csv"):
            return pd.read_csv(f, dtype=str, usecols=lambda c: c in cols)
        return pd.read_excel(f, dtype=str, usecols=lambda c: c in cols, engine="openpyxl")


def wells(cache: Path) -> pd.DataFrame:
    raw = fetch.download(SOURCES["AB"]["wells"], cache / "AB" / "ST_37_Excel.zip")
    with zipfile.ZipFile(raw) as z:
        print("  reading ST37 surface holes ...", flush=True)
        sh = _read(z, _find(z, "st37_sh"), ["Well_Licence_Number", "SH_Actual_Latitude", "SH_Actual_Longitude",
                                             "Licence_Surface_Location_Label"])
        print("  reading ST37 production strings (largest sheet) ...", flush=True)
        ps = _read(z, _find(z, "production_strings"), [
            "Prod_String_UWI", "Well_Licence_Number", "Well_Name", "Licensee", "Field_Code", "Pool_Code",
            "Status_Fluid", "Status_Mode", "Status_Type", "Scheme_Type", "Licence_Status", "Licence_Status_Date",
            "Final_Total_Depth", "Max_True_Vertical_Depth", "Spud_Date"])
    for df in (sh, ps):
        df["lic"] = clean_str(df["Well_Licence_Number"]).str.lstrip("0")
    df = ps.merge(sh.drop(columns="Well_Licence_Number"), on="lic", how="left")
    td = pd.to_numeric(df["Final_Total_Depth"], errors="coerce")
    tvd = pd.to_numeric(df["Max_True_Vertical_Depth"], errors="coerce")
    mode, typ = clean_str(df["Status_Mode"]), clean_str(df["Status_Type"])
    out = pd.DataFrame({
        "uwi": df["Prod_String_UWI"],
        "well_name": clean_str(df["Well_Name"]),
        "licensee": clean_str(df["Licensee"]),
        "status": mode.where(mode.notna(), typ),
        "status_date": df["Licence_Status_Date"],
        "fluid": clean_str(df["Status_Fluid"]),
        "field": clean_str(df["Field_Code"]),
        "formation": clean_str(df["Pool_Code"]),
        "spud_date": df["Spud_Date"],
        "total_depth_m": td,
        "horizontal": (tvd > 0) & (td - tvd > 400),
        "lat": df["SH_Actual_Latitude"],
        "lon": df["SH_Actual_Longitude"],
    })
    return finish_wells(out, "AB")


def production(cache: Path, months: list[str]) -> pd.DataFrame:
    return petrinex.production("AB", months, cache)
