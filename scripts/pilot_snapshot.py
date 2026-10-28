"""Build site data from a previously downloaded Petrinex extract (petrinex_area.csv from the Colab notebook).

This is how the repository's committed snapshot was made: Alberta, Whitecourt area, battery level.
The full-basin data comes from `python -m wellscope run` (see .github/workflows/pipeline.yml).
"""
import sys
from pathlib import Path

import pandas as pd

from wellscope import analytics
from wellscope.schema import WELL_COLS, finish_production

src, out = Path(sys.argv[1]), Path(sys.argv[2] if len(sys.argv) > 2 else "site/data")
raw = pd.read_csv(src, dtype=str, low_memory=False)
raw = raw[(raw.ActivityID == "PROD") & raw.ProductID.isin(["OIL", "GAS", "COND", "WATER"])].copy()
raw["Volume"] = pd.to_numeric(raw.Volume, errors="coerce").fillna(0)
raw["Hours"] = pd.to_numeric(raw.Hours, errors="coerce")
col = {"OIL": "oil_m3", "GAS": "gas_e3m3", "COND": "cond_m3", "WATER": "water_m3"}
raw["p"] = raw.ProductID.map(col)
w = raw.pivot_table(index=["ReportingFacilityID", "ProductionMonth", "OperatorName", "ReportingFacilityLocation"],
                    columns="p", values="Volume", aggfunc="sum", fill_value=0).reset_index()
h = raw.groupby(["ReportingFacilityID", "ProductionMonth"], as_index=False).Hours.max()
w = w.merge(h, on=["ReportingFacilityID", "ProductionMonth"], how="left")
w = w.rename(columns={"ReportingFacilityID": "entity_id", "ProductionMonth": "month", "OperatorName": "operator",
                      "ReportingFacilityLocation": "location", "Hours": "hours"})
w["entity_type"], w["facility_id"] = "facility", w["entity_id"]
w["month"] = pd.to_datetime(w["month"].str[:7], format="%Y-%m")
prod = finish_production(w, "AB")
wells = pd.DataFrame(columns=WELL_COLS)
meta = analytics.build(wells, prod, out, {"AB": {"name": "Alberta", "pages": [
    "https://www.petrinex.ca/public-data/apd/"]}}, min_n=4)
print(meta["counts"], meta["latest"], meta["backtest"])
