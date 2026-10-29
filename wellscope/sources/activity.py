"""Drilling activity: newly issued licences and drilling starts, the leading indicators of where companies are spending.

* Licences: Petrinex Well Licence downloads for Alberta and Saskatchewan (issue date, licensee, surface location,
  target formation, horizontal or not), Manitoba Petroleum Branch new well approvals.
* Drilling: spud dates from the AER ST37 and Petrinex Saskatchewan well lists, and rig-release dates from BC.
Every event has: date, kind ("licence" | "spud" | "rig_release"), province, licensee, location, lat, lon, formation, hz.
"""
from __future__ import annotations

from pathlib import Path

import pandas as pd

from .. import fetch, locate
from ..config import SOURCES
from ..schema import to_date
from . import petrinex

COLS = ["date", "kind", "province", "licensee", "licence", "location", "uwi", "formation", "hz", "lat", "lon", "loc_precision"]


def _pick(df, *names):
    c = fetch.pick(df, *names, required=False)
    return df[c] if c else pd.Series(pd.NA, index=df.index)


def petrinex_licences(jur: str, cache: Path, since: pd.Timestamp) -> pd.DataFrame:
    df = petrinex.infra(jur, "Well Licence", cache)
    date = to_date(_pick(df, "Licence Issue Date", "LicenceIssueDate"))
    keep = date >= since
    df, date = df[keep], date[keep]
    loc = _pick(df, "Licence Location", "LicenceLocation").astype("string")
    op = _pick(df, "Drilling Operation Type", "DrillingOperationType").astype("string").str.upper()
    target = _pick(df, "Terminating Formation", "TerminatingFormation", "Projected Formation", "ProjectedFormation", "Target Pool", "TargetPool")
    out = pd.DataFrame({
        "date": date, "kind": "licence", "province": jur,
        "licensee": _pick(df, "Licensee Name", "LicenseeName").astype("string").str.strip(),
        "licence": _pick(df, "Licence Number", "LicenceNumber").astype("string").str.strip().str.lstrip("0"),
        "location": loc, "uwi": pd.NA, "formation": target.astype("string").str.strip(),
        "hz": op.str.contains("HORIZ", na=False),
    })
    return out


def mb_licences(cache: Path, since: pd.Timestamp) -> pd.DataFrame:
    df = pd.read_excel(fetch.download(SOURCES["MB"]["new_wells"], cache / "MB" / "new_wells.xlsx"), dtype=str)
    df.columns = [str(c).strip() for c in df.columns]
    date = to_date(_pick(df, "Licence Date", "Date Licensed", "Approval Date", "Date", "Issue Date"))
    lat = pd.to_numeric(_pick(df, "Latitude", "Lat", "Surface Latitude"), errors="coerce")
    lon = pd.to_numeric(_pick(df, "Longitude", "Long", "Surface Longitude"), errors="coerce")
    out = pd.DataFrame({
        "date": date, "kind": "licence", "province": "MB",
        "licensee": _pick(df, "Company", "Licensee", "Company Name").astype("string").str.strip(),
        "licence": _pick(df, "Licence", "Licence No", "Licence Number", "Lic No").astype("string").str.strip(),
        "location": _pick(df, "Location", "UWI", "Licensed Location").astype("string"),
        "uwi": pd.NA, "formation": _pick(df, "Target Formation", "Formation", "Pool").astype("string"),
        "hz": _pick(df, "Well Type", "Deviation", "Type").astype("string").str.upper().str.contains("HOR", na=False),
        "lat": lat, "lon": lon.where(lon.isna() | (lon < 0), -lon),
    })
    return out[out["date"].isna() | (out["date"] >= since)]


def drilling(wells: pd.DataFrame, since: pd.Timestamp) -> pd.DataFrame:
    """Spud (AB, SK, MB) or rig-release (BC) dates from the provincial well lists."""
    w = wells.dropna(subset=["spud_date"])
    w = w[pd.to_datetime(w["spud_date"], errors="coerce") >= since]
    # one event per wellbore: the first production string of each licence
    w = w.sort_values("uwi").drop_duplicates(subset=["province", "licence"] if w["licence"].notna().any() else ["uwi"])
    return pd.DataFrame({
        "date": pd.to_datetime(w["spud_date"]), "kind": w["province"].map(lambda p: "rig_release" if p == "BC" else "spud"),
        "province": w["province"], "licensee": w["licensee"], "licence": w["licence"], "location": pd.NA, "uwi": w["uwi"],
        "formation": w["formation"], "hz": w["horizontal"].fillna(False), "lat": w["lat"], "lon": w["lon"],
        "loc_precision": w["loc_precision"],
    })


def collect(wells: pd.DataFrame, cache: Path, provinces: list[str], days: int = 400) -> tuple[pd.DataFrame, dict]:
    since = pd.Timestamp.today().normalize() - pd.Timedelta(days=days)
    parts, problems = [drilling(wells, since)], {}
    for jur in [p for p in ("AB", "SK") if p in provinces]:
        try:
            parts.append(petrinex_licences(jur, cache, since))
        except Exception as e:
            problems[f"{jur} licences"] = repr(e)[:400]
    if "MB" in provinces:
        try:
            parts.append(mb_licences(cache, since))
        except Exception as e:
            problems["MB licences"] = repr(e)[:400]
    ev = pd.concat([p for p in parts if len(p)], ignore_index=True) if any(len(p) for p in parts) else pd.DataFrame(columns=COLS)
    for c in COLS:
        if c not in ev:
            ev[c] = pd.NA
    need = ev["lat"].isna() & ev["location"].notna()
    if need.any():
        loc = ev.loc[need, "location"].map(locate.locate)
        ev.loc[need, "lat"] = [x[0] for x in loc]
        ev.loc[need, "lon"] = [x[1] for x in loc]
        ev.loc[need, "loc_precision"] = [x[2] for x in loc]
    ev["date"] = pd.to_datetime(ev["date"], errors="coerce")
    ev = ev.dropna(subset=["date"])
    return ev[COLS].reset_index(drop=True), problems
