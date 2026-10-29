"""Download helpers with an on-disk cache, nested-zip handling and tolerant CSV/Excel readers."""
from __future__ import annotations

import io
import os
import re
import time
import urllib.error
import urllib.request
import zipfile
from pathlib import Path

import pandas as pd

UA = {"User-Agent": "Mozilla/5.0 (WellScope open-data pipeline; +https://github.com/kosherite/wellscope)"}


def download(url: str, dest: Path, retries: int = 3, timeout: int = 600, quiet: bool = False,
             max_age_hours: float | None = 20) -> Path:
    """Stream ``url`` to ``dest``, reusing a cached copy younger than ``max_age_hours`` (None = keep forever).

    Lists that change (well lists, licences) must refresh every run; old production months never change.
    """
    dest = Path(dest)
    if dest.exists() and dest.stat().st_size > 0:
        age_h = (time.time() - dest.stat().st_mtime) / 3600
        if max_age_hours is None or age_h < max_age_hours:
            return dest
    if os.environ.get("WELLSCOPE_OFFLINE"):
        raise RuntimeError(f"offline: {url} is not cached")
    dest.parent.mkdir(parents=True, exist_ok=True)
    tmp = dest.with_suffix(dest.suffix + ".part")
    last = None
    for attempt in range(1, retries + 1):
        try:
            req = urllib.request.Request(url, headers=UA)
            with urllib.request.urlopen(req, timeout=timeout) as r, open(tmp, "wb") as f:
                done = 0
                while True:
                    chunk = r.read(1 << 20)
                    if not chunk:
                        break
                    f.write(chunk)
                    done += len(chunk)
            tmp.rename(dest)
            if not quiet:
                print(f"  fetched {url} ({done / 1e6:,.1f} MB)", flush=True)
            return dest
        except (urllib.error.URLError, TimeoutError, ConnectionError, OSError) as e:
            last = e
            print(f"  attempt {attempt} failed for {url}: {e}", flush=True)
            time.sleep(5 * attempt)
    raise RuntimeError(f"Could not download {url}: {last}")


def unzip_bytes(data: bytes, member_hint: str | None = None) -> bytes:
    """Petrinex wraps files in zips inside zips; unwrap until we reach a non-zip payload."""
    while data[:2] == b"PK":
        z = zipfile.ZipFile(io.BytesIO(data))
        names = [n for n in z.namelist() if not n.endswith("/")]
        if member_hint:
            hits = [n for n in names if member_hint.lower() in n.lower()]
            names = hits or names
        data = z.read(names[0])
    return data


def read_table(data: bytes, **kw) -> pd.DataFrame:
    """CSV with tolerant decoding (publishers mix UTF-8 and Windows-1252)."""
    kw.setdefault("dtype", str)
    kw.setdefault("low_memory", False)
    try:
        return pd.read_csv(io.BytesIO(data), encoding="utf-8", **kw)
    except UnicodeDecodeError:
        return pd.read_csv(io.BytesIO(data), encoding="cp1252", **kw)


def norm_col(c: str) -> str:
    return re.sub(r"[^a-z0-9]+", "_", str(c).strip().lower()).strip("_")


def pick(df: pd.DataFrame, *aliases: str, required: bool = True) -> str | None:
    """Find a column by any of several normalised aliases. Raise with the real column list if missing,
    so a publisher's format change shows up as a clear error in the pipeline log."""
    cols = {norm_col(c): c for c in df.columns}
    for a in aliases:
        if norm_col(a) in cols:
            return cols[norm_col(a)]
    # loose contains-match as a fallback
    for a in aliases:
        na = norm_col(a)
        for nc, orig in cols.items():
            if na and na in nc:
                return orig
    if required:
        raise KeyError(f"None of {aliases} found. Columns are: {list(df.columns)}")
    return None


def cache_dir() -> Path:
    return Path(os.environ.get("WELLSCOPE_CACHE", "data/raw"))
