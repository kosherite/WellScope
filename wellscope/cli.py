"""Command line entry point.

    python -m wellscope probe                     # print each source's columns (run this when a publisher changes a file)
    python -m wellscope run --provinces AB,SK,BC,MB --months 36 --out site/data
"""
from __future__ import annotations

import argparse
import json
import os
import shutil
import subprocess
import sys
import traceback
from pathlib import Path

import pandas as pd

from . import analytics, fetch, mapdata
from .config import SOURCES
from .schema import WELL_COLS
from .sources import ab, bc, mb, sk

ADAPTERS = {"AB": ab, "SK": sk, "BC": bc, "MB": mb}


def month_list(end: str | None, n: int) -> list[str]:
    end_p = pd.Period(end, "M") if end else (pd.Timestamp.today() - pd.DateOffset(months=2)).to_period("M")
    return [str(p) for p in pd.period_range(end=end_p, periods=n, freq="M")]


def notice(title: str, msg: str, level: str = "notice") -> None:
    """Surface a one-line result as a GitHub Actions annotation (visible on the run page and via the API)."""
    if os.environ.get("GITHUB_ACTIONS"):
        msg = msg.replace("%", "%25").replace("\r", "").replace("\n", " ")[:3500]
        print(f"::{level} title={title}::{msg}", flush=True)


def cmd_run(a) -> int:
    cache = Path(a.cache)
    months = month_list(a.end, a.months)
    wells, prods, used, problems = [], [], {}, {}
    diag = __import__("collections").defaultdict(list)
    for prov in [p.strip().upper() for p in a.provinces.split(",") if p.strip()]:
        mod = ADAPTERS[prov]
        print(f"\n== {prov}: wells", flush=True)
        try:
            w = mod.wells(cache)
            print(f"  {len(w):,} wells, {w['lat'].notna().mean():.0%} located", flush=True)
            diag[prov].append(f"WELLS {len(w):,}; located {w['lat'].notna().mean():.1%}; "
                              f"status {w['status_group'].value_counts().to_dict()}; sample {w['uwi'].head(3).tolist()}")
            other = w.loc[w["status_group"].eq("Other"), "status"].astype(str).value_counts().head(25).to_dict()
            diag[prov].append(f"UNMAPPED STATUS {other}")
            wells.append(w)
        except Exception as e:  # keep going: one publisher's change should not sink the whole basin
            problems[f"{prov} wells"] = repr(e)
            notice(f"{prov} wells FAILED", traceback.format_exc()[-1500:], "warning")
            traceback.print_exc()
        print(f"== {prov}: production", flush=True)
        try:
            p = mod.production(cache, months)
            print(f"  {len(p):,} entity-months, {p['entity_id'].nunique():,} entities", flush=True)
            wl = p[p["entity_type"] == "well"]["entity_id"]
            matched = wl.isin(set(wells[-1]["uwi"])).mean() if wells and wells[-1]["province"].iloc[0] == prov and len(wl) else None
            diag[prov].append(f"PRODUCTION {len(p):,} entity-months; {p['entity_id'].nunique():,} entities; "
                                         f"well-level {p['entity_type'].eq('well').mean():.1%}; months {p['month'].min():%Y-%m} to "
                                         f"{p['month'].max():%Y-%m}; well ids matched to well list {matched}; sample {wl.head(3).tolist()}")
            if matched is not None and matched < 0.98:
                miss = wl[~wl.isin(set(wells[-1]["uwi"]))].drop_duplicates()
                diag[prov].append(f"UNMATCHED {len(miss):,} ids, e.g. {miss.sample(min(15, len(miss)), random_state=1).tolist()}")
            prods.append(p)
        except Exception as e:
            problems[f"{prov} production"] = repr(e)
            notice(f"{prov} production FAILED", traceback.format_exc()[-1500:], "warning")
            traceback.print_exc()
        used[prov] = {"name": SOURCES[prov]["name"], "pages": SOURCES[prov]["pages"]}
        notice(f"{prov} summary", " || ".join(diag[prov]))
    if not prods:
        print("No production loaded from any province", file=sys.stderr)
        notice("Build FAILED", f"No production loaded from any province. Problems: {problems}", "error")
        return 1
    W = pd.concat(wells, ignore_index=True) if wells else pd.DataFrame(columns=WELL_COLS)
    P = pd.concat(prods, ignore_index=True)
    if a.parquet:
        Path(a.parquet).mkdir(parents=True, exist_ok=True)
        W.to_parquet(Path(a.parquet) / "wells.parquet", index=False)
        P.to_parquet(Path(a.parquet) / "production.parquet", index=False)
    print("\n== map data", flush=True)
    out = Path(a.out)
    try:
        meta = mapdata.build(W, P, out, used, Path(a.work))
        tiles(Path(a.work), out)
    except Exception:
        notice("Map data FAILED", traceback.format_exc()[-2500:], "error")
        raise
    meta["problems"] = problems
    (out / "meta.json").write_text(json.dumps(meta, default=str))
    print(f"done: {meta['counts']}  problems: {list(problems) or 'none'}")
    size = sum(f.stat().st_size for f in out.rglob("*") if f.is_file()) / 1e6
    notice("WellScope build", f"counts={meta['counts']} latest={meta['latest']} site_data_mb={size:.0f}")
    if a.valuation:     # parked: the decline/PV screener, written beside the map data but not linked from the site
        print("\n== valuation analytics (parked)", flush=True)
        analytics.build(W, P, out / "valuation", used)
    for k, v in problems.items():
        notice(f"Problem: {k}", v, "warning")
    return 0 if not problems or a.allow_partial else 2


def tiles(work: Path, out: Path) -> None:
    """Turn the line-delimited GeoJSON into one PMTiles file with tippecanoe (skipped if it isn't installed)."""
    exe = os.environ.get("TIPPECANOE") or shutil.which("tippecanoe")
    if not exe:
        print("  tippecanoe not found: wells.pmtiles not built (install it, or set TIPPECANOE)", flush=True)
        return
    cmd = [exe, "-o", str(out / "wells.pmtiles"), "--force", "-q", "-P", "-Z3", "-z12", "--drop-densest-as-needed",
           "-n", "WellScope wells", "-A", "AER, Petrinex, BCER, Manitoba Petroleum Branch",
           "-L", f"dots:{work / 'dots.geojsonl'}", "-L", f"wells:{work / 'wells.geojsonl'}",
           "-L", f"laterals:{work / 'laterals.geojsonl'}"]
    print("  " + " ".join(cmd), flush=True)
    subprocess.run(cmd, check=True)
    print(f"  wells.pmtiles {(out / 'wells.pmtiles').stat().st_size / 1e6:.1f} MB", flush=True)


def cmd_probe(a) -> int:
    """Download each source and print its columns and first rows."""
    cache = Path(a.cache)
    months = month_list(a.end, 1)
    checks = {
        "AB petrinex vol": lambda: fetch.read_table(fetch.unzip_bytes(
            __import__("wellscope.sources.petrinex", fromlist=["x"]).month_file("AB", months[0], cache).read_bytes()), nrows=5),
        "SK petrinex vol": lambda: fetch.read_table(fetch.unzip_bytes(
            __import__("wellscope.sources.petrinex", fromlist=["x"]).month_file("SK", months[0], cache).read_bytes()), nrows=5),
        "SK well infrastructure": lambda: sk.petrinex.infra("SK", "Well Infrastructure", cache).head(5),
        "BC well index": lambda: fetch.read_table(fetch.download(SOURCES["BC"]["well_index"], cache / "BC" / "well_index.csv").read_bytes(), nrows=5),
        "BC production": lambda: (notice("BC production files", bc.describe(cache)), pd.DataFrame({"see": ["notice"]}))[1],
        "MB uwi list": lambda: pd.read_excel(fetch.download(SOURCES["MB"]["uwi_list"], cache / "MB" / "uwi_weekly.xlsx"), nrows=5),
        "MB production": lambda: next(mb._sheets(fetch.download(SOURCES["MB"]["production"][0], cache / "MB" / "wmp_0.zip")))[1].head(5),
    }
    ok = True
    for name, fn in checks.items():
        print(f"\n### {name}")
        try:
            df = fn()
            print("columns:", list(df.columns))
            print(df.head(3).to_string(max_colwidth=30))
            first = df.head(1).to_dict("records")[0] if len(df) else {}
            notice(f"Probe OK: {name}", f"columns={list(df.columns)} first_row={ {k: str(v)[:40] for k, v in first.items()} }")
        except Exception as e:
            ok = False
            print("FAILED:", repr(e))
            notice(f"Probe FAILED: {name}", repr(e), "warning")
    return 0 if ok else 3


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(prog="wellscope")
    sub = ap.add_subparsers(dest="cmd", required=True)
    r = sub.add_parser("run", help="download, process and publish site data")
    r.add_argument("--provinces", default="AB,SK,BC,MB")
    r.add_argument("--months", type=int, default=36)
    r.add_argument("--end", help="last production month, YYYY-MM (default: two months ago)")
    r.add_argument("--cache", default="data/raw")
    r.add_argument("--out", default="site/data")
    r.add_argument("--parquet", default="data/build")
    r.add_argument("--work", default="data/work", help="scratch folder for tile inputs")
    r.add_argument("--valuation", action="store_true", help="also build the parked decline/PV screener data")
    r.add_argument("--allow-partial", action="store_true", help="exit 0 even if a province failed")
    r.set_defaults(fn=cmd_run)
    pr = sub.add_parser("probe", help="print each source's columns")
    pr.add_argument("--cache", default="data/raw")
    pr.add_argument("--end")
    pr.set_defaults(fn=cmd_probe)
    a = ap.parse_args(argv)
    return a.fn(a)


if __name__ == "__main__":
    sys.exit(main())
