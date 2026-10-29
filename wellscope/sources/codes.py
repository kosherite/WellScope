"""Code tables that turn numeric field and pool codes into names (Petrinex Alberta Field and Pool Codes report)."""
from __future__ import annotations

from pathlib import Path

import pandas as pd

from .. import fetch
from ..config import SOURCES

LAST: dict = {}   # what the last load found, for the pipeline's diagnostics


def ab_field_pool(cache: Path) -> tuple[dict, dict]:
    """Returns ({field_code: field_name}, {(field_code, pool_code) or pool_code: pool_name}). Empty on failure."""
    try:
        raw = fetch.download(SOURCES["AB"]["pool_codes"], cache / "AB" / "PRAFieldandPoolCodes.csv").read_bytes()
        df = fetch.read_table(raw)
    except Exception as e:  # names are a nicety; never fail the build over them
        print(f"  pool codes unavailable: {e}")
        LAST.update(error=repr(e)[:300])
        return {}, {}
    p = lambda *a: fetch.pick(df, *a, required=False)  # noqa: E731
    fc, fn = p("Field Code", "FieldCode", "Field"), p("Field Name", "FieldName")
    pc, pn = p("Pool Code", "PoolCode", "Pool Deposit Code", "Pool"), p("Pool Name", "PoolName", "Pool Deposit Name")
    norm = lambda s: s.astype(str).str.strip().str.lstrip("0")  # noqa: E731
    fields, pools = {}, {}
    if fc and fn:
        fields = dict(zip(norm(df[fc]), df[fn].astype(str).str.strip()))
    if pc and pn:
        names = df[pn].astype(str).str.strip()
        pools.update(dict(zip(norm(df[pc]), names)))
        if fc:
            pools.update(dict(zip(zip(norm(df[fc]), norm(df[pc])), names)))
    LAST.update(fields=len(fields), pools=len(pools), columns=list(df.columns)[:12], head=df.head(3).astype(str).values.tolist())
    print(f"  pool codes: {len(fields):,} fields, {len(pools):,} pools; columns {list(df.columns)[:8]}")
    return fields, pools
