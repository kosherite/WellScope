"""Parse Canadian well identifiers and survey locations, and turn them into approximate lat/lon.

Two survey systems cover the WCSB:

* Dominion Land Survey (DLS), used in Alberta, Saskatchewan, Manitoba and BC's Peace River Block.
  UWI form: ``100/06-06-001-01W4/00`` -> LE / LSD-SEC-TWP-RGE W MER / ES.
* National Topographic System (NTS), used for most of northeast BC.
  UWI form: ``200/A-001-B/093-P-09/00`` -> quarter unit, unit, block / map, letter, sheet.

Coordinates from these formulas are approximate. DLS ignores road allowances and correction lines, so
expect errors of roughly 0.5 to 3 km. Wherever a source publishes surveyed coordinates, prefer those and
keep the ``loc_precision`` column honest.
"""
from __future__ import annotations

import math
import re
from dataclasses import dataclass

# ---------------------------------------------------------------- DLS
# Meridians (longitude, degrees west). W1 is the Principal Meridian.
MERIDIAN_LON = {1: 97.4579, 2: 102.0, 3: 106.0, 4: 110.0, 5: 114.0, 6: 118.0}
TWP_KM = 9.656064          # 6 miles
SEC_KM = TWP_KM / 6
KM_PER_DEG_LAT = 111.2
LAT0 = 49.0                # township 1 starts at the 49th parallel

_DLS = re.compile(
    r"(?:(?P<le>\d{2,3})/)?"                      # location exception, e.g. 100
    r"(?:(?P<lsd>\d{1,2})-)?(?P<sec>\d{1,2})-(?P<twp>\d{1,3})-(?P<rge>\d{1,2})\s*W\s*(?P<mer>\d)"
    r"(?:/(?P<es>\d{1,2}))?",
    re.I,
)


@dataclass(frozen=True)
class DLS:
    lsd: int | None
    sec: int
    twp: int
    rge: int
    mer: int

    @property
    def township_key(self) -> str:
        return f"T{self.twp:03d}-R{self.rge:02d}W{self.mer}"

    @property
    def label(self) -> str:
        lsd = f"{self.lsd:02d}-" if self.lsd else ""
        return f"{lsd}{self.sec:02d}-{self.twp:03d}-{self.rge:02d}W{self.mer}"


def parse_dls(text: str | None) -> DLS | None:
    if text is None or not isinstance(text, str) and str(text) in ("<NA>", "nan", "NaT", "None"):
        return None
    if not text:
        return None
    m = _DLS.search(str(text).replace(" ", ""))
    if not m:
        return None
    d = m.groupdict()
    sec, twp, rge, mer = int(d["sec"]), int(d["twp"]), int(d["rge"]), int(d["mer"])
    lsd = int(d["lsd"]) if d["lsd"] else None
    if not (1 <= sec <= 36 and 1 <= twp <= 130 and 1 <= rge <= 34 and 1 <= mer <= 6):
        return None
    if lsd is not None and not 1 <= lsd <= 16:
        return None
    return DLS(lsd, sec, twp, rge, mer)


def _sec_offsets(sec: int) -> tuple[int, int]:
    """(row from south, column from east) of a section in its township (boustrophedon numbering)."""
    row = (sec - 1) // 6
    col = (sec - 1) % 6 if row % 2 == 0 else 5 - (sec - 1) % 6
    return row, col


def _lsd_offsets(lsd: int) -> tuple[int, int]:
    row = (lsd - 1) // 4
    col = (lsd - 1) % 4 if row % 2 == 0 else 3 - (lsd - 1) % 4
    return row, col


def dls_to_latlon(d: DLS) -> tuple[float, float]:
    """Approximate centre of the LSD (or section) as (lat, lon)."""
    srow, scol = _sec_offsets(d.sec)
    if d.lsd:
        lrow, lcol = _lsd_offsets(d.lsd)
        north_km = (d.twp - 1) * TWP_KM + srow * SEC_KM + (lrow + 0.5) * SEC_KM / 4
        west_km = (d.rge - 1) * TWP_KM + scol * SEC_KM + (lcol + 0.5) * SEC_KM / 4
    else:
        north_km = (d.twp - 1) * TWP_KM + (srow + 0.5) * SEC_KM
        west_km = (d.rge - 1) * TWP_KM + (scol + 0.5) * SEC_KM
    lat = LAT0 + north_km / KM_PER_DEG_LAT
    km_per_deg_lon = 111.32 * math.cos(math.radians(lat))
    lon = -(MERIDIAN_LON[d.mer] + west_km / km_per_deg_lon)
    return round(lat, 5), round(lon, 5)


# ---------------------------------------------------------------- NTS (BC)
_NTS = re.compile(
    r"(?P<qu>[A-D])-(?P<unit>\d{1,3})-(?P<block>[A-L])\s*/\s*(?P<map>\d{2,3})-?(?P<letter>[A-P])-?(?P<sheet>\d{1,2})",
    re.I,
)
# Letter -> (row from south, col from east) in the 4x4 lettered grid of a map area.
_LETTER = {}
for i, ch in enumerate("ABCDEFGHIJKLMNOP"):
    r = i // 4
    c = i % 4 if r % 2 == 0 else 3 - i % 4
    _LETTER[ch] = (r, c)


def _map_area_sw(map_no: int) -> tuple[float, float]:
    """South-west corner (lat, lon west positive) of a 1:250k NTS map area such as 093 or 094."""
    series, area = divmod(map_no, 10)       # 093 -> series 9, area 3
    # South of 68N: series 8 spans 112-120W, 9 spans 120-128W, 10 spans 128-136W, 11 spans 136-144W.
    # Area 2 starts at 48N, area 3 at 52N, area 4 at 56N (4 degrees each).
    lat = 40.0 + 4.0 * area
    lon_east = 48.0 + 8.0 * series          # east edge of the map area (deg west)
    return lat, lon_east


def nts_to_latlon(text: str | None) -> tuple[float, float] | None:
    """Approximate centre of an NTS quarter-unit location like ``A-001-B/093-P-09``.

    Valid south of 68N, which covers all of BC. Map area 093 spans 52-56N, 120-128W; each map area has
    16 lettered map sheets (1 deg x 2 deg), each sheet 16 numbered sheets (15' x 30'), each sheet
    12 blocks A-L (5' x 7.5'), each block 100 units (0.5' x 0.75'), each unit 4 quarter units.
    """
    if not text:
        return None
    m = _NTS.search(str(text).replace(" ", ""))
    if not m:
        return None
    g = m.groupdict()
    map_no, letter, sheet = int(g["map"]), g["letter"].upper(), int(g["sheet"])
    if not 1 <= sheet <= 16:
        return None
    unit = int(g["unit"])
    if not 1 <= unit <= 100:
        return None
    lat0, lon_e = _map_area_sw(map_no)
    lrow, lcol = _LETTER[letter]
    lat = lat0 + lrow * 1.0
    lon = lon_e + lcol * 2.0
    srow, scol = _LETTER["ABCDEFGHIJKLMNOP"[sheet - 1]]          # same snake ordering for numbered sheets
    lat += srow * 0.25
    lon += scol * 0.5
    bi = "ABCDEFGHIJKL".index(g["block"].upper())
    brow = bi // 4
    bcol = bi % 4 if brow % 2 == 0 else 3 - bi % 4
    lat += brow * (5 / 60)
    lon += bcol * (7.5 / 60)
    urow = (unit - 1) // 10
    ucol = (unit - 1) % 10 if urow % 2 == 0 else 9 - (unit - 1) % 10
    lat += urow * (0.5 / 60)
    lon += ucol * (0.75 / 60)
    qi = "ABCD".index(g["qu"].upper())
    qrow, qcol = {0: (0, 0), 1: (0, 1), 2: (1, 1), 3: (1, 0)}[qi]
    lat += (qrow + 0.5) * (0.25 / 60)
    lon += (qcol + 0.5) * (0.375 / 60)
    return round(lat, 5), round(-lon, 5)


# ---------------------------------------------------------------- UWI helpers
def normalize_uwi(text: str | None) -> str | None:
    """Uppercase, strip spaces; keep the identifier's own punctuation."""
    if text is None:
        return None
    s = re.sub(r"\s+", "", str(text)).upper()
    return s or None


def locate(text: str | None) -> tuple[float | None, float | None, str]:
    """Best-effort (lat, lon, precision) from any DLS or NTS text."""
    if text is None or not isinstance(text, str) and str(text) in ("<NA>", "nan", "NaT", "None"):
        return None, None, "unplaced"
    d = parse_dls(text)
    if d:
        lat, lon = dls_to_latlon(d)
        return lat, lon, "dls-lsd" if d.lsd else "dls-section"
    n = nts_to_latlon(text)
    if n:
        return n[0], n[1], "nts"
    return None, None, "unplaced"


def area_key(lat: float | None, lon: float | None, dlat: float = 0.1, dlon: float = 0.15) -> str | None:
    """A province-independent grid cell (about township size) so the whole basin shares one map grid."""
    if lat is None or lon is None or (isinstance(lat, float) and math.isnan(lat)):
        return None
    return f"{math.floor(lat / dlat)}_{math.floor(-lon / dlon)}"


def area_bounds(key: str, dlat: float = 0.1, dlon: float = 0.15) -> tuple[float, float, float, float]:
    i, j = (int(x) for x in key.split("_"))
    return i * dlat, -(j + 1) * dlon, (i + 1) * dlat, -j * dlon     # south, west, north, east
