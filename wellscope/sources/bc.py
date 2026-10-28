"""British Columbia: BC Energy Regulator (BCER) open downloads.

* ``well_index.csv`` (confirmed Oct 2026): ``WA, Well Name, Bottom Hole, Mode, Fluid, Oper, RR Date, Area, Form,
  UWI`` with compact UWIs such as ``200D080H092G0300``. No coordinates; wells are placed from the UWI.
* ``prod_csv.zip``: zone production split into several period files (e.g. 1954-2006, later years). Each file
  may start with a title line before its header, so the header row is detected.
"""
from __future__ import annotations

import io
import re
import zipfile
from pathlib import Path

import pandas as pd

from .. import fetch
from ..config import SOURCES
from ..schema import clean_str, finish_production, finish_wells


def _col(df, name):
    return df[name] if name in df.columns else pd.NA


def wells(cache: Path) -> pd.DataFrame:
    raw = fetch.download(SOURCES["BC"]["well_index"], cache / "BC" / "well_index.csv").read_bytes()
    df = fetch.read_table(raw)
    df.columns = [str(c).strip() for c in df.columns]
    if "UWI" not in df.columns:
        raise KeyError(f"BC well index has no UWI column; columns are {list(df.columns)}")
    name = clean_str(_col(df, "Well Name")).str.replace(r"\s+", " ", regex=True)
    mode, fluid, oper = clean_str(_col(df, "Mode")), clean_str(_col(df, "Fluid")), clean_str(_col(df, "Oper"))
    # "Oper" is the operation type (PROD, INJ, DISP, UND...), not the operator. Injection or disposal wells are service wells.
    service = oper.fillna("").str.upper().str.contains("INJ|DISP|STOR|OBS|SRC|SOURCE", regex=True)
    out = pd.DataFrame({
        "uwi": clean_str(df["UWI"]),
        "well_name": name,
        "licence": clean_str(_col(df, "WA")).str.lstrip("0"),      # BC well authorization number
        # The index has no operator column; BC well names start with the operator's abbreviation (e.g. "CNRL HZ ALTARES").
        "licensee": name.str.extract(r"^([A-Z0-9&\-\.]+)", expand=False),
        "status": mode.where(~service, "WATER INJECTION"),
        "status_text": (fluid.fillna("") + " " + mode.fillna("") + " " + oper.fillna("")).str.strip().replace("", pd.NA),
        "fluid": fluid,
        "field": clean_str(_col(df, "Area")),
        "formation": clean_str(_col(df, "Form")),
        "spud_date": _col(df, "RR Date"),          # rig release date: the closest published drilling date
    })
    return finish_wells(out, "BC")


def _period_members(z: zipfile.ZipFile) -> list[str]:
    """Data files ordered newest period first (by the largest year in the file name)."""
    names = [n for n in z.namelist() if n.lower().endswith((".csv", ".txt")) and not n.endswith("/")]
    def last_year(n):
        ys = [int(y) for y in re.findall(r"(19\d{2}|20\d{2})", n)]
        if re.search(r"present|current|curr", n, re.I):
            return 9999
        return max(ys) if ys else 0
    return sorted(names, key=last_year, reverse=True)


def _read_member(data: bytes) -> pd.DataFrame:
    head = data[:20000].decode("utf-8", "replace").splitlines()
    skip = next((i for i, line in enumerate(head[:30]) if re.search(r"\buwi\b", line, re.I)), 0)
    return fetch.read_table(data, skiprows=skip)


def describe(cache: Path) -> str:
    """Member list and first lines, for the probe."""
    zp = fetch.download(SOURCES["BC"]["production"], cache / "BC" / "prod_csv.zip")
    with zipfile.ZipFile(zp) as z:
        info = [f"{i.filename} ({i.file_size / 1e6:.1f} MB)" for i in z.infolist()]
        first = _period_members(z)[0]
        lines = z.read(first)[:1500].decode("utf-8", "replace").splitlines()[:6]
    return f"members={info} newest={first} first_lines={lines}"


def production(cache: Path, months: list[str]) -> pd.DataFrame:
    zp = fetch.download(SOURCES["BC"]["production"], cache / "BC" / "prod_csv.zip")
    start = pd.Period(months[0], "M").to_timestamp()
    parts = []
    with zipfile.ZipFile(zp) as z:
        for name in _period_members(z):
            df = _read_member(z.read(name))
            df.columns = [str(c).strip() for c in df.columns]
            p = lambda *a, req=False: fetch.pick(df, *a, required=req)  # noqa: E731
            uwi = p("UWI", "Well UWI", req=True)
            per = p("Prod Period", "Production Period", "Prod_Period", "Period", "Prod Date", "Month")
            if per:
                month = pd.to_datetime(df[per].astype(str).str.replace(r"[^0-9]", "", regex=True).str[:6], format="%Y%m", errors="coerce")
            else:
                y, m = p("Year", "Prod Year", req=True), p("Month", "Prod Month", req=True)
                month = pd.to_datetime(df[y].astype(str) + "-" + df[m].astype(str).str.zfill(2), format="%Y-%m", errors="coerce")
            num = lambda *a: pd.to_numeric(df[p(*a)], errors="coerce") if p(*a) else 0.0  # noqa: E731
            days = num("Prod Days", "Production Days", "Days On", "Days")
            out = pd.DataFrame({
                "entity_id": df[uwi], "entity_type": "well", "month": month,
                "operator": df[p("Operator", "Oper", "Operator Name")] if p("Operator", "Oper", "Operator Name") else pd.NA,
                "facility_id": pd.NA, "location": pd.NA,
                "oil_m3": num("Oil Prod Vol", "Oil (m3)", "Oil Volume", "Oil"),
                "gas_e3m3": num("Gas Prod Vol", "Gas (e3m3)", "Gas Volume", "Gas"),
                "cond_m3": num("Cond Prod Vol", "Condensate", "Cond Volume", "Cond"),
                "water_m3": num("Water Prod Vol", "Water (m3)", "Water Volume", "Water"),
                "hours": days * 24 if not isinstance(days, float) else num("Hours", "Prod Hours"),
            })
            out = out[out["month"] >= start]
            if len(out):
                parts.append(out)
            elif month.max() < start:
                break        # files are ordered newest first; older ones can't contain the window
    if not parts:
        raise RuntimeError(f"No BC production rows on or after {months[0]}")
    return finish_production(pd.concat(parts, ignore_index=True), "BC")
