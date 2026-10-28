import io
import json
import zipfile

import numpy as np
import pandas as pd
import pytest

from wellscope import analytics, locate, model
from wellscope.schema import canon_uwi, finish_production, finish_wells, status_group
from wellscope.sources import petrinex


def test_uwi_forms_join():
    a = canon_uwi("100/06-06-001-01W4/00")
    assert a == canon_uwi("00/06-06-001-01W4/0") == canon_uwi("ABWI100060600101W400") == "00/06-06-001-01W4/0"
    assert canon_uwi("102/16-21-063-18W5/02") == "02/16-21-063-18W5/2"
    assert canon_uwi("200/D-096-H/094-A-16/00") == "00/D-096-H/094-A-16/0"


def test_locations_near_known_towns():
    lat, lon, p = locate.locate("06-36-060-12W5")      # Whitecourt area
    assert abs(lat - 54.14) < 0.15 and abs(lon + 115.68) < 0.2 and p == "dls-lsd"
    lat, lon, p = locate.locate("A-001-A/094-A-10")     # near Fort St. John
    assert 56.0 < lat < 57.0 and -121.5 < lon < -120.0 and p == "nts"
    assert locate.locate("garbage")[2] == "unplaced"


def test_status_groups():
    assert status_group("PUMPING") == "Producing"
    assert status_group("SUSPENDED") == "Inactive"
    assert status_group("ABANDONED ZONE") == "Abandoned"
    assert status_group("WATER INJECTION") == "Service"


def _petrinex_zip(rows):
    csv = pd.DataFrame(rows).to_csv(index=False).encode()
    inner = io.BytesIO(); zipfile.ZipFile(inner, "w").writestr("Vol_2026-01-AB.CSV", csv)
    outer = io.BytesIO(); zipfile.ZipFile(outer, "w").writestr("Vol_2026-01-AB.zip", inner.getvalue())
    return outer.getvalue()


def test_petrinex_month_splits_wells_and_facilities():
    base = dict(ProductionMonth="2026-01", OperatorName="ACME OIL LTD.", ReportingFacilityID="ABBT0000001",
                ReportingFacilityType="BT", ReportingFacilityLocation="06-36-060-12W5", ActivityID="PROD")
    rows = [
        dict(base, ProductID="OIL", FromToID="ABWI100063606012W500", FromToIDType="WI", Volume="31.8", Hours="744"),
        dict(base, ProductID="GAS", FromToID="ABWI100063606012W500", FromToIDType="WI", Volume="10", Hours="744"),
        dict(base, ProductID="OIL", FromToID="***", FromToIDType="", Volume="5", Hours="***"),
        dict(base, ProductID="OIL", ActivityID="DISP", FromToID="ABPL0000009", FromToIDType="PL", Volume="36", Hours=""),
    ]
    wide = petrinex.parse_month(_petrinex_zip(rows))
    prod = finish_production(wide, "AB")
    well = prod[prod.entity_type == "well"].iloc[0]
    assert well.entity_id == "00/06-36-060-12W5/0"
    assert well.oil_m3 == pytest.approx(31.8) and well.gas_e3m3 == pytest.approx(10) and well.hours == 744
    fac = prod[prod.entity_type == "facility"].iloc[0]
    assert fac.entity_id == "ABBT0000001" and fac.oil_m3 == pytest.approx(5) and fac.location == "06-36-060-12W5"
    assert len(prod) == 2      # DISP row ignored


def test_decline_fit_recovers_known_curve():
    t = np.arange(24) / 12
    y = model.arps(t, 500, 0.8, 0.5)
    f = model.fit_fixed_b(y, 0.5)
    assert f["di"] == pytest.approx(0.8, rel=0.02) and f["r2"] > 0.999
    assert model.backtest(model.arps(np.arange(30) / 12, 500, 0.8, 0.5)) == pytest.approx(0, abs=0.01)


def synthetic(n_wells=60, months=30, seed=3):
    rng = np.random.default_rng(seed)
    mths = pd.period_range("2023-08", periods=months, freq="M").to_timestamp()
    wells, prod = [], []
    for i in range(n_wells):
        lsd, sec = 1 + i % 16, 1 + (i // 16) % 36
        uwi = f"100/{lsd:02d}-{sec:02d}-060-{12 + i % 2:02d}W5/00"
        onset = 0 if i < 40 else rng.integers(3, 15)
        qi, di = rng.uniform(80, 300), rng.uniform(0.5, 1.2)
        op = "ACME OIL LTD." if i % 3 else "BETA ENERGY INC."
        wells.append(dict(uwi=uwi, well_name=f"ACME {i}", licensee=op, status="PUMPING" if i < 55 else "SUSPENDED",
                          fluid="CRUDE OIL", total_depth_m=1800, spud_date="2020-01-01", horizontal=i % 2 == 0,
                          lat=None, lon=None))
        for k, m in enumerate(mths):
            if k < onset or i >= 55:
                continue
            q = model.arps((k - onset + (24 if onset == 0 else 0)) / 12, qi, di, 0.6)
            prod.append(dict(entity_id=uwi, entity_type="well", month=m, operator=op, facility_id="ABBT1",
                             location=None, oil_m3=q * 30.4 / 6.29 * 0.8, gas_e3m3=q * 30.4 * 0.2 * 6 / 35.3,
                             cond_m3=0, water_m3=q * 2, hours=720))
    W = finish_wells(pd.DataFrame(wells), "AB")
    P = finish_production(pd.DataFrame(prod), "AB")
    return W, P


def test_end_to_end_build(tmp_path):
    W, P = synthetic()
    meta = analytics.build(W, P, tmp_path, {"AB": {"name": "Alberta", "pages": []}}, min_n=3)
    assert meta["counts"]["entities"] == 55
    basin = json.loads((tmp_path / "basin.json").read_text())
    b = basin["basin"]
    assert b["boe"] > 0 and 60 < b["oil_pct"] < 100
    assert b["decline"] is not None and 10 < b["decline"] < 80
    assert b["type_curve"]["p10"][0] >= b["type_curve"]["p50"][0] >= b["type_curve"]["p90"][0]
    assert b["pdp"]["fits"] and len(b["history"]["boe"]) == 30
    cells = json.loads((tmp_path / "cells.json").read_text())
    assert cells and all("b" in c for c in cells)
    c0 = json.loads((tmp_path / "cells" / f"{cells[0]['id']}.json").read_text())
    assert c0["wells_list"] and len(c0["wells_list"][0]["spark"]) <= 24
    ops = json.loads((tmp_path / "operators.json").read_text())
    names = {o["name"] for o in ops}
    assert "Acme Oil Ltd." in names and ops[0]["boe"] >= ops[-1]["boe"]
    acme = next(o for o in ops if o["name"] == "Acme Oil Ltd.")
    assert acme["inactive"] >= 1     # licensee liability joined by normalised name


def test_ab_st37_reader(tmp_path):
    from wellscope.sources import ab
    sh = pd.DataFrame({"Well_Licence_Number": ["0065081", "0078503"], "Licensee": ["x", "y"],
                       "SH_Actual_Latitude": [54.1, 54.2], "SH_Actual_Longitude": [-115.7, -115.8],
                       "Licence_Surface_Location_Label": ["06-06-060-12W5", "07-06-060-12W5"]})
    ps = pd.DataFrame({"Prod_String_UWI": ["00/06-06-060-12W5/0", "02/07-06-060-12W5/0"],
                       "Well_Licence_Number": [" 0065081", " 0078503"], "Well_Name": ["A 6-6  ", "B 7-6"],
                       "Licensee": ["Cenovus Energy Inc.", "Acme Ltd."], "Field_Code": ["998", "961"],
                       "Pool_Code": [None, "158098"], "Status_Fluid": ["CRUDE OIL     ", "GAS"],
                       "Status_Mode": ["PUMPING     ", "SUSPENDED"], "Status_Type": ["x", "y"], "Scheme_Type": [None, None],
                       "Licence_Status": ["Issued", "Issued"], "Licence_Status_Date": ["2020-01-01", "2021-01-01"],
                       "Final_Total_Depth": ["3800", "1500"], "Max_True_Vertical_Depth": ["1900", "0"],
                       "Spud_Date": ["2015-03-01", "2001-01-01"]})
    zp = tmp_path / "AB" / "ST_37_Excel.zip"
    zp.parent.mkdir(parents=True)
    with zipfile.ZipFile(zp, "w") as z:
        for name, df in {"ST_37_Excel/ST37_SH.xlsx": sh, "ST_37_Excel/ST37_ Production_Strings.xlsx": ps}.items():
            b = io.BytesIO(); df.to_excel(b, index=False); z.writestr(name, b.getvalue())
    w = ab.wells(tmp_path)
    assert list(w["uwi"]) == ["00/06-06-060-12W5/0", "02/07-06-060-12W5/0"]
    assert list(w["status_group"]) == ["Producing", "Inactive"]
    assert list(w["horizontal"]) == [True, False]
    assert w["loc_precision"].eq("surveyed").all() and w["lat"].iloc[0] == pytest.approx(54.1)


def test_mb_wide_months():
    from wellscope.sources import mb
    df = pd.DataFrame({"UWI": ["100.14-14-009-29W1.00"] * 2, "NAME": ["TUNDRA OIL & GAS LIMITED"] * 2,
                       "FLUID CODE": ["OIL", "WATER"], "YEAR": ["2026", "2026"],
                       **{m: ["10", "40"] if m in ("JAN", "FEB") else ["0", "0"] for m in mb.MONTHS}})
    out = finish_production(mb._standardize(df), "MB")
    assert len(out) == 2 and out.entity_id.iloc[0] == "00/14-14-009-29W1/0"
    assert out.oil_m3.tolist() == [10, 10] and out.water_m3.tolist() == [40, 40]


def test_wells_with_missing_values_and_no_coordinates():
    df = pd.DataFrame({"uwi": ["200D080H092G0300", "100060608613W600", "junk"], "status": [pd.NA, "ABAN", None],
                       "fluid": [pd.NA, "OIL", None], "lat": [pd.NA, pd.NA, pd.NA], "lon": [None, None, None]})
    w = finish_wells(df, "BC")
    assert list(w["status_group"]) == ["Other", "Abandoned", "Other"]
    assert w["lat"].notna().sum() == 2 and set(w["loc_precision"]) == {"nts", "dls-lsd", "unplaced"}


def test_build_without_well_lists(tmp_path):
    _, P = synthetic()
    from wellscope.schema import WELL_COLS
    meta = analytics.build(pd.DataFrame(columns=WELL_COLS), P, tmp_path, {"AB": {"name": "Alberta", "pages": []}}, min_n=3)
    assert meta["counts"]["entities"] == 55 and meta["counts"]["wells"] == 0


def test_mapdata_exports(tmp_path):
    from wellscope import mapdata
    W, P = synthetic()
    W.loc[0, "bh_lat"], W.loc[0, "bh_lon"] = W.loc[0, "lat"] + 0.015, W.loc[0, "lon"]
    W = W.astype({"lat": object, "lon": object, "bh_lat": object, "bh_lon": object})   # as after concatenating provinces
    P = pd.concat([P, P.head(1).assign(entity_id="00/01-01-061-12W5/0")])              # a producing well not on the list
    W["licence"] = [str(1000 + i) for i in range(len(W))]
    meta = mapdata.build(W, P, tmp_path / "site", {"AB": {"name": "Alberta", "pages": []}}, tmp_path / "work")
    assert meta["counts"]["wells"] == 61 and meta["counts"]["not_on_lists"] == 1 and meta["counts"]["laterals"] == 1
    first = json.loads((tmp_path / "work" / "wells.geojsonl").read_text().splitlines()[0])
    assert set(first["properties"]) == {"u", "s", "o", "b"}
    key = mapdata.shard_key(W.uwi.iloc[0])
    assert key == "W5-060-12"
    shard = json.loads((tmp_path / "site" / "twp" / f"{key}.json").read_text())
    rec = shard["wells"][W.uwi.iloc[0]]
    assert rec["d"] == "100/01-01-060-12W5/00" and rec["s"] == "oil" and len(rec["pr"][0]) == len(shard["months"])
    lic = json.loads((tmp_path / "site" / "lic" / "00.json").read_text())
    assert lic["1000"] == [["AB", W.uwi.iloc[0]]]
    assert mapdata.symbol("Abandoned", "Other", False) == "dry" and mapdata.symbol("Inactive", "Gas", True) == "gas_susp"
    assert mapdata.shard_key("00/D-080-H/092-G-03/0") == "N092G03"
