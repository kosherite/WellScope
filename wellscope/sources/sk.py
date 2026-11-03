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
    out = petrinex.well_infra_frame(petrinex.infra("SK", "Well Infrastructure", cache))
    try:
        targets = petrinex.licence_targets("SK", cache)
        out["target_formation"] = out["licence"].map(targets)
    except Exception as e:  # a nicety: never fail the build over it
        print(f"  SK licence targets unavailable: {e}")
    return finish_wells(out, "SK")


def production(cache: Path, months: list[str]) -> pd.DataFrame:
    return petrinex.production("SK", months, cache)
