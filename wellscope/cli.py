"""Command line entry point.

    python -m wellscope probe                     # print each source's columns (run this when a publisher changes a file)
    python -m wellscope run --provinces AB,SK,BC,MB --months 36 --out site/data
"""
from __future__ import annotations

import argparse
import os
import sys
import traceback
from pathlib import Path

import pandas as pd

from . import analytics, fetch
from .config import SOURCES
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
    for prov in [p.strip().upper() for p in a.provinces.split(",") if p.strip()]:
        mod = ADAPTERS[prov]
        print(f"\n== {prov}: wells", flush=True)
        try:
            w = mod.wells(cache)
            print(f"  {len(w):,} wells, {w['lat'].notna().mean():.0%} located", flush=True)
            wells.append(w)
        except Exception as e:  # keep going: one publisher's change should not sink the whole basin
            problems[f"{prov} wells"] = repr(e)
            traceback.print_exc()
        print(f"== {prov}: production", flush=True)
        try:
            p = mod.production(cache, months)
            print(f"  {len(p):,} entity-months, {p['entity_id'].nunique():,} entities", flush=True)
            prods.append(p)
        except Exception as e:
            problems[f"{prov} production"] = repr(e)
            traceback.print_exc()
        used[prov] = {"name": SOURCES[prov]["name"], "pages": SOURCES[prov]["pages"]}
    if not prods:
        print("No production loaded from any province", file=sys.stderr)
        return 1
    W = pd.concat(wells, ignore_index=True) if wells else pd.DataFrame(columns=analytics.__dict__.get("WELL_COLS", []))
    P = pd.concat(prods, ignore_index=True)
    if a.parquet:
        Path(a.parquet).mkdir(parents=True, exist_ok=True)
        W.to_parquet(Path(a.parquet) / "wells.parquet", index=False)
        P.to_parquet(Path(a.parquet) / "production.parquet", index=False)
    print("\n== analytics", flush=True)
    meta = analytics.build(W, P, Path(a.out), used)
    meta["problems"] = problems
    (Path(a.out) / "meta.json").write_text(__import__("json").dumps(meta, default=str))
    print(f"done: {meta['counts']}  problems: {list(problems) or 'none'}")
    notice("WellScope build", f"counts={meta['counts']} latest={meta['latest']} backtest={meta['backtest']} "
                              f"location_check={meta['location_check']}")
    for k, v in problems.items():
        notice(f"Problem: {k}", v, "warning")
    return 0 if not problems or a.allow_partial else 2


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
        "BC production": lambda: fetch.read_table(fetch.unzip_bytes(
            fetch.download(SOURCES["BC"]["production"], cache / "BC" / "prod_csv.zip").read_bytes(), ".csv"), nrows=5),
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
