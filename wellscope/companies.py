"""Resolve every regulator spelling of an operator to one company (and a ticker when there is one).

The mapping lives in ``data/companies.yml`` so it can be edited without touching code. Names that aren't in the
file still resolve to a single company per spelling-insensitive key (case, punctuation and Ltd./Inc./Corp. ignored).
"""
from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path

import yaml

SUFFIX = re.compile(r"\b(LTD|LIMITED|INC|INCORPORATED|CORP|CORPORATION|ULC|CO|COMPANY|LP|PARTNERSHIP|THE)\b\.?")
DEFAULT_FILE = Path(__file__).resolve().parent.parent / "data" / "companies.yml"


def key(name) -> str | None:
    if name is None:
        return None
    s = str(name).strip()
    if not s or s.lower() in ("nan", "none", "<na>", "unknown"):
        return None
    s = s.upper().replace("&", " AND ")
    s = re.sub(r"[^A-Z0-9 ]", " ", s)
    s = SUFFIX.sub(" ", s)
    s = re.sub(r"\s+", " ", s).strip()
    return s or None


def slug(s: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", str(s).lower()).strip("-")[:60] or "unknown"


def pretty(name: str) -> str:
    """Title-case ALL-CAPS regulator names, keeping short acronyms (ARC, CNRL, ULC) as they are."""
    s = str(name).strip()
    if not s.isupper():
        return s
    out = []
    for w in s.split():
        core = re.sub(r"[^A-Z0-9]", "", w)
        out.append(w if (len(core) <= 3 and core not in ("OIL", "GAS", "AND", "THE", "LTD", "INC")) or core in ("CNRL", "ULC")
                   else w.capitalize())
    return " ".join(out)


@dataclass(frozen=True)
class Company:
    id: str            # slug used in URLs and file names, e.g. "tou" or "acme-oil"
    name: str          # display name
    ticker: str | None


class Resolver:
    def __init__(self, path: Path | str | None = None):
        path = Path(path or DEFAULT_FILE)
        data = yaml.safe_load(path.read_text()) if path.exists() else {}
        self.by_key: dict[str, Company] = {}
        tickers = {}
        for ticker, d in (data or {}).items():
            d = d or {}
            target = d.get("merged_into")
            tickers[str(ticker)] = (d.get("name") or str(ticker), target)
        for ticker, (name, target) in tickers.items():
            final = target or ticker
            fname = tickers.get(final, (name, None))[0]
            private = bool(((data or {}).get(ticker) or {}).get("private"))
            co = Company(slug(fname), fname, None) if private else Company(slug(final), fname, final)
            for alias in [name, ticker] + list(((data or {}).get(ticker) or {}).get("aliases") or []):
                k = key(alias)
                if k:
                    self.by_key.setdefault(k, co)
        self.unmatched: dict[str, int] = {}

    def resolve(self, name, weight: int = 1) -> Company:
        k = key(name)
        if k is None:
            return Company("unknown", "Unknown", None)
        co = self.by_key.get(k)
        if co:
            return co
        self.unmatched[k] = self.unmatched.get(k, 0) + weight
        return Company(slug(k), pretty(str(name)), None)
