"""The one table layout every province is converted into, plus shared cleaning helpers."""
from __future__ import annotations

import re

import numpy as np
import pandas as pd

from . import locate

WELL_COLS = ["uwi", "province", "well_name", "licence", "licensee", "status", "status_text", "status_group", "status_date",
             "fluid", "field", "formation", "spud_date", "total_depth_m", "horizontal", "lat", "lon", "loc_precision",
             "bh_lat", "bh_lon", "surface_loc"]
PROD_COLS = ["entity_id", "entity_type", "province", "month", "operator", "facility_id", "location",
             "oil_m3", "gas_e3m3", "cond_m3", "water_m3", "hours"]

# Location exception codes can contain letters (e.g. "F1" for water source wells, "1A", "D0").
_DLS_UWI = re.compile(r"(?:(\d)?([0-9A-Z]{2})/)?(\d{2})-(\d{2})-(\d{3})-(\d{2})W(\d)(?:/(\d{1,2}))?", re.I)
_DLS_COMPACT = re.compile(r"^(?:[A-Z]{2}WI)?(\d)([0-9A-Z]{2})(\d{2})(\d{2})(\d{3})(\d{2})W(\d)(\d{1,2})$", re.I)
_NTS_UWI = re.compile(r"(?:(\d)?([0-9A-Z]{2})/)?([A-D])-(\d{3})-([A-L])/(\d{3})-([A-P])-(\d{2})(?:/(\d{1,2}))?", re.I)
_NTS_COMPACT = re.compile(r"^(?:[A-Z]{2}WI)?(\d)([0-9A-Z]{2})([A-D])(\d{3})([A-L])(\d{3})([A-P])(\d{2})(\d{1,2})$", re.I)


def canon_uwi(text) -> str | None:
    """One join key for every way a UWI is written across AER, Petrinex, BCER and Manitoba.

    ``100/06-06-001-01W4/00``, ``00/06-06-001-01W4/0`` and Petrinex's ``ABWI100060600101W400`` all become
    ``00/06-06-001-01W4/0`` (two-digit location exception, last digit of the event sequence).
    """
    if text is None or (isinstance(text, float) and np.isnan(text)):
        return None
    s = re.sub(r"\s+", "", str(text)).upper()
    s = re.sub(r"^(\d{3})\.(.*)\.(\d{1,2})$", r"\1/\2/\3", s)
    m = _DLS_COMPACT.match(s)
    if m:
        _, le, lsd, sec, twp, rge, mer, es = m.groups()
        return f"{le}/{lsd}-{sec}-{twp}-{rge}W{mer}/{es[-1]}"
    m = _NTS_COMPACT.match(s)
    if m:
        _, le, q, unit, blk, mp, let, sh, es = m.groups()
        return f"{le}/{q}-{unit}-{blk}/{mp}-{let}-{sh}/{es[-1]}"
    m = _DLS_UWI.search(s)
    if m:
        _, le, lsd, sec, twp, rge, mer, es = m.groups()
        return f"{le or '00'}/{lsd}-{sec}-{twp}-{rge}W{mer}/{(es or '0')[-1]}"
    m = _NTS_UWI.search(s)
    if m:
        _, le, q, unit, blk, mp, let, sh, es = m.groups()
        return f"{le or '00'}/{q}-{unit}-{blk}/{mp}-{let}-{sh}/{(es or '0')[-1]}"
    return s


def status_group(raw) -> str:
    """Collapse every province's status vocabulary (words and abbreviations) into the groups analysts filter by."""
    s = "" if _missing(raw) else str(raw).upper().strip()
    if not s or s in ("NAN", "NONE", "NOT APPLICABLE", "<NA>"):
        return "Other"
    w = s.replace("-", " ").split()
    first = w[0] if w else ""
    if "ABAND" in s or "JUNK" in s or "RECLAIM" in s or "J & A" in s or s.startswith(("ABZ", "ABR", "ABN")) or \
            first in ("ABD", "ABDG", "ABAN", "AB", "JNK", "RAB") or "CERTIFICATE" in s:
        return "Abandoned"
    if "SUSP" in s or "SHUT" in s or "INACTIVE" in s or "CLOSED" in s or first in ("SI", "CAPP", "CAP", "CAPPED", "SIP", "DSUS", "WOSR", "WOO"):
        return "Inactive"
    if any(k in s for k in ("PUMP", "FLOW", "GAS LIFT", "PRODUC", "ACTIVE", "OPERATING", "PLUNGER")) or \
            first in ("PMP", "FLW", "PROD", "GLIFT", "PRD", "OIL", "GAS", "ACT", "COOP", "COMINGLED") or s == "RESUMED COOP":
        return "Producing"
    if any(k in s for k in ("INJ", "DISP", "STORAGE", "OBSERV", "SOURCE", "CAVERN")) or first in ("WINJ", "GINJ", "DSPL", "OBS", "WAG", "WIW", "SWD", "WSW", "SSW", "BIW", "SW GD") or s == "RESUMED SWD":
        return "Service"
    if any(k in s for k in ("DRILL", "CASED", "LICEN", "PERMIT", "LOCATION", "AUTHORI", "TEST", "COMPLET", "SPUD")) or \
            first in ("DRL", "DRIL", "DR", "CASE", "COMP", "LOC", "D&C", "DST", "LOG"):
        return "Pre-production"
    return "Other"


def _missing(v) -> bool:
    try:
        return v is None or bool(pd.isna(v))
    except (TypeError, ValueError):
        return False


def fluid_group(raw) -> str:
    s = "" if _missing(raw) else str(raw).upper()
    if "BITUMEN" in s or "OIL SAND" in s:
        return "Bitumen"
    if "OIL" in s:
        return "Oil"
    if "GAS" in s or "METHANE" in s:
        return "Gas"
    if "WATER" in s:
        return "Water"
    return "Other"


def clean_str(s: pd.Series) -> pd.Series:
    s = s.astype("string").str.strip()
    return s.mask(s.isin(["", "nan", "None", "NaN", "Not Applicable"]))


def to_date(s: pd.Series) -> pd.Series:
    if pd.api.types.is_datetime64_any_dtype(s):
        return s
    t = s.astype("string").str.strip()
    out = pd.to_datetime(t, errors="coerce", format="%Y%m%d")
    miss = out.isna() & t.notna()
    if miss.any():
        out[miss] = pd.to_datetime(t[miss], errors="coerce", format="mixed", dayfirst=False)
    return out


def finish_wells(df: pd.DataFrame, province: str) -> pd.DataFrame:
    """Fill derived columns, locate wells without surveyed coordinates, and return WELL_COLS only."""
    df = df.copy()
    df["province"] = province
    for c in WELL_COLS:
        if c not in df:
            df[c] = pd.NA
    df["uwi"] = df["uwi"].map(canon_uwi)
    df["status_group"] = df["status"].map(status_group)
    df["status_text"] = df["status_text"].where(df["status_text"].notna(), df["status"])
    df["fluid"] = df["fluid"].map(fluid_group)
    df["bh_lat"] = pd.to_numeric(df["bh_lat"], errors="coerce")
    df["bh_lon"] = pd.to_numeric(df["bh_lon"], errors="coerce")
    df["lat"] = pd.to_numeric(df["lat"], errors="coerce")
    df["lon"] = pd.to_numeric(df["lon"], errors="coerce")
    df.loc[df["lat"].notna(), "loc_precision"] = df.loc[df["lat"].notna(), "loc_precision"].fillna("surveyed")
    need = df["lat"].isna()
    if need.any():
        located = df.loc[need, "uwi"].map(locate.locate)
        df.loc[need, "lat"] = np.array([np.nan if x[0] is None else x[0] for x in located], dtype=float)
        df.loc[need, "lon"] = np.array([np.nan if x[1] is None else x[1] for x in located], dtype=float)
        df["loc_precision"] = df["loc_precision"].astype("object")
        df.loc[need, "loc_precision"] = [x[2] for x in located]
    df["total_depth_m"] = pd.to_numeric(df["total_depth_m"], errors="coerce")
    df["spud_date"] = to_date(df["spud_date"])
    df["status_date"] = to_date(df["status_date"])
    df["horizontal"] = df["horizontal"].fillna(False).astype(bool)
    df = df.dropna(subset=["uwi"]).drop_duplicates("uwi", keep="last")
    return df[WELL_COLS].reset_index(drop=True)


def finish_production(df: pd.DataFrame, province: str) -> pd.DataFrame:
    df = df.copy()
    df["province"] = province
    for c in PROD_COLS:
        if c not in df:
            df[c] = pd.NA if c not in ("oil_m3", "gas_e3m3", "cond_m3", "water_m3", "hours") else 0.0
    for c in ("oil_m3", "gas_e3m3", "cond_m3", "water_m3", "hours"):
        df[c] = pd.to_numeric(df[c], errors="coerce").fillna(0.0).astype("float32")
    df["month"] = pd.to_datetime(df["month"]).dt.to_period("M").dt.to_timestamp()
    df.loc[df["entity_type"].eq("well"), "entity_id"] = df.loc[df["entity_type"].eq("well"), "entity_id"].map(canon_uwi)
    keys = ["entity_id", "entity_type", "province", "month"]
    agg = {"oil_m3": "sum", "gas_e3m3": "sum", "cond_m3": "sum", "water_m3": "sum", "hours": "max",
           "operator": "last", "facility_id": "last", "location": "last"}
    df = df.dropna(subset=["entity_id", "month"]).groupby(keys, as_index=False, observed=True).agg(agg)
    return df[PROD_COLS]
