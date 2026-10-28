"""Petrinex public data for Alberta and Saskatchewan.

Conventional Volumetric files list, for every reporting facility and month, the activity (PROD, DISP...),
the product (OIL, GAS, WATER, COND) and the From/To counterpart. For production at a battery the
counterpart is the producing well, with that well's hours, so summing PROD rows by From/To well gives
well-level production. Rows whose counterpart is confidential ("***") stay at facility level.
"""
from __future__ import annotations

from pathlib import Path

import pandas as pd

from .. import fetch
from ..config import PETRINEX_INFRA, PETRINEX_VOL
from ..schema import finish_production

VOL_COLS = ["ProductionMonth", "OperatorName", "ReportingFacilityID", "ReportingFacilityType",
            "ReportingFacilityLocation", "ActivityID", "ProductID", "FromToID", "FromToIDType", "Volume", "Hours"]
PRODUCTS = {"OIL": "oil_m3", "GAS": "gas_e3m3", "COND": "cond_m3", "WATER": "water_m3"}


def month_file(jur: str, month: str, cache: Path) -> Path:
    raw = cache / jur / "vol" / f"{month}.bin"
    fetch.download(PETRINEX_VOL.format(jur=jur, month=month), raw)
    return raw


def parse_month(data: bytes) -> pd.DataFrame:
    """Reduce one raw monthly file to production rows, one per entity and month, products as columns."""
    body = fetch.unzip_bytes(data)
    head = fetch.read_table(body, nrows=0)
    use = [c for c in VOL_COLS if c in head.columns]
    missing = set(VOL_COLS) - set(use) - {"FromToIDType"}
    if missing:
        raise KeyError(f"Petrinex volumetric file is missing {sorted(missing)}; columns are {list(head.columns)}")
    df = fetch.read_table(body, usecols=use)
    df = df[(df["ActivityID"] == "PROD") & df["ProductID"].isin(PRODUCTS)]
    df["Volume"] = pd.to_numeric(df["Volume"], errors="coerce").fillna(0)
    df["Hours"] = pd.to_numeric(df["Hours"], errors="coerce")
    ft = df.get("FromToIDType", pd.Series("", index=df.index)).fillna("").str.upper()
    fid = df["FromToID"].fillna("")
    is_well = ft.eq("WI") | fid.str.upper().str.slice(2, 4).eq("WI")
    df["entity_type"] = is_well.map({True: "well", False: "facility"})
    df["entity_id"] = fid.where(is_well, df["ReportingFacilityID"])
    df["product"] = df["ProductID"].map(PRODUCTS)
    df["ReportingFacilityLocation"] = df["ReportingFacilityLocation"].fillna("")
    wide = df.pivot_table(index=["entity_id", "entity_type", "ProductionMonth", "OperatorName", "ReportingFacilityID",
                                 "ReportingFacilityLocation"],
                          columns="product", values="Volume", aggfunc="sum", fill_value=0).reset_index()
    hrs = df.groupby(["entity_id", "ProductionMonth"], as_index=False)["Hours"].max()
    wide = wide.merge(hrs, on=["entity_id", "ProductionMonth"], how="left")
    wide = wide.rename(columns={"ProductionMonth": "month", "OperatorName": "operator",
                                "ReportingFacilityID": "facility_id", "ReportingFacilityLocation": "location",
                                "Hours": "hours"})
    wide["month"] = pd.to_datetime(wide["month"].astype(str).str[:7], format="%Y-%m", errors="coerce")
    return wide


def facility_locations(jur: str, months: list[str], cache: Path) -> pd.DataFrame:
    """Facility ID -> legal location from the most recent file (used for facility-level rows)."""
    out = []
    for m in months[-1:]:
        body = fetch.unzip_bytes(month_file(jur, m, cache).read_bytes())
        df = fetch.read_table(body, usecols=["ReportingFacilityID", "ReportingFacilityLocation", "ReportingFacilityName"])
        out.append(df.drop_duplicates("ReportingFacilityID"))
    return pd.concat(out, ignore_index=True).drop_duplicates("ReportingFacilityID", keep="last")


def production(jur: str, months: list[str], cache: Path) -> pd.DataFrame:
    parts = []
    for m in months:
        try:
            raw = month_file(jur, m, cache)
        except RuntimeError as e:
            print(f"  skipping {jur} {m}: {e}")
            continue
        p = parse_month(raw.read_bytes())
        print(f"  {jur} {m}: {len(p):,} entity rows, {p['entity_type'].eq('well').mean():.0%} well-level", flush=True)
        parts.append(p)
    if not parts:
        raise RuntimeError(f"No Petrinex volumetric months loaded for {jur}")
    return finish_production(pd.concat(parts, ignore_index=True), jur)


def infra(jur: str, name: str, cache: Path) -> pd.DataFrame:
    raw = cache / jur / "infra" / f"{name.replace(' ', '_')}.bin"
    fetch.download(PETRINEX_INFRA.format(jur=jur, name=name.replace(" ", "%20")), raw)
    return fetch.read_table(fetch.unzip_bytes(raw.read_bytes()))
