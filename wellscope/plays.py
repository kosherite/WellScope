"""Group pool and formation names into the plays analysts talk about (Montney, Duvernay, Clearwater, Bakken...),
then into a short, fixed list of categories per province (``category``).

Categories are named after formations and groups as the regulators list them (AER Table of Formations, BCER
formation codes, Saskatchewan and Manitoba pool names); a few are the industry's names for a group of formations
produced together (Deep Basin, shallow gas). Anything outside the list is "Other".

Pool names from the regulators look like "MONTNEY A", "BLUESKY-GETHING (ABC)" or "VIKING-1". The first
matching keyword wins, so more specific names come first. Anything unmatched keeps a tidied version of its own name.
"""
from __future__ import annotations

import re

PLAYS = [
    ("Montney", ["MONTNEY"]),
    ("Duvernay", ["DUVERNAY"]),
    ("Clearwater", ["CLEARWATER"]),
    ("Bakken / Three Forks", ["BAKKEN", "THREE FORKS", "TORQUAY"]),
    ("Viking", ["VIKING"]),
    ("Cardium", ["CARDIUM"]),
    ("Charlie Lake", ["CHARLIE LAKE", "BOUNDARY LAKE"]),
    ("Spirit River (Deep Basin)", ["SPIRIT RIVER", "FALHER", "WILRICH", "NOTIKEWIN", "BLUESKY", "GETHING", "CADOMIN", "CADOTTE"]),
    ("Belly River", ["BELLY RIVER"]),
    ("Jean Marie (Redknife)", ["JEAN MARIE", "REDKNIFE"]),
    ("Horn River (Muskwa / Otter Park / Evie)", ["MUSKWA", "OTTER PARK", "EVIE", "HORN RIVER"]),
    ("Baldonnel", ["BALDONNEL", "PARDONET"]),
    ("Doig / Halfway", ["DOIG", "HALFWAY"]),
    ("Horseshoe Canyon (CBM)", ["HORSESHOE CANYON", "EDMONTON", "MANNVILLE COAL"]),
    ("Glauconitic / Mannville", ["GLAUCONITIC", "GLAUC", "ELLERSLIE", "OSTRACOD", "LLOYDMINSTER", "SPARKY", "GENERAL PETROLEUM",
                                 "REX", "WASECA", "COLONY", "MCLAREN", "CUMMINGS", "DINA", "MANNVILLE", "BASAL QUARTZ"]),
    ("Wabamun / Nisku / Leduc", ["WABAMUN", "NISKU", "LEDUC", "SWAN HILLS", "BEAVERHILL", "SLAVE POINT", "KEG RIVER", "GILWOOD"]),
    ("Mississippian (Midale / Frobisher)", ["MIDALE", "FROBISHER", "TILSTON", "SOURIS VALLEY", "ALIDA", "LODGEPOLE", "RUNDLE",
                                           "PEKISKO", "BANFF", "ELKTON", "TURNER VALLEY", "DEBOLT", "SHUNDA"]),
    ("Shaunavon / Upper Shaunavon", ["SHAUNAVON"]),
    ("Medicine Hat / Milk River (shallow gas)", ["MEDICINE HAT", "MILK RIVER", "SECOND WHITE SPECKS", "SECOND WHITE SPECKLED"]),
    ("Oil sands (in situ)", ["MCMURRAY", "WABISKAW", "GRAND RAPIDS"]),
    ("Dunlevy / Nikanassin", ["DUNLEVY", "NIKANASSIN"]),
]


def play(name, province: str | None = None) -> str | None:
    if name is None:
        return None
    s = str(name).strip().upper()
    if not s or s in ("NAN", "<NA>", "NONE", "NOT APPLICABLE"):
        return None
    if s.startswith("COMMINGLED") or s.startswith("CMGL") or "COMMINGLED CODE" in s:
        return "Commingled (several zones)"
    for label, keys in PLAYS:
        if any(k in s for k in keys):
            return label
    if s.isdigit():                       # an unresolved code (BC formation codes), keep it recognisable
        return f"Formation code {s}"
    s = re.sub(r"[\(\[].*?[\)\]]", "", s)
    s = re.sub(r"\b(UNDEFINED|UNDEF|POOL|[A-Z]{1,2}\d*|\d+)\b$", "", s).strip(" -")
    return s.title() or None


COMMINGLED = "Commingled (several zones)"
OTHER = "Other"

# play label -> category, per province. A play missing from a province's map is "Other" there.
_AB = {
    "Montney": "Montney", "Duvernay": "Duvernay", "Spirit River (Deep Basin)": "Spirit River / Deep Basin",
    "Dunlevy / Nikanassin": "Spirit River / Deep Basin", "Cardium": "Cardium", "Viking": "Viking",
    "Clearwater": "Clearwater", "Glauconitic / Mannville": "Mannville", "Belly River": "Belly River",
    "Charlie Lake": "Charlie Lake", "Baldonnel": "Charlie Lake", "Doig / Halfway": "Doig / Halfway",
    "Wabamun / Nisku / Leduc": "Devonian carbonates", "Jean Marie (Redknife)": "Devonian carbonates",
    "Mississippian (Midale / Frobisher)": "Mississippian", "Horseshoe Canyon (CBM)": "Shallow gas & CBM",
    "Medicine Hat / Milk River (shallow gas)": "Shallow gas & CBM", "Oil sands (in situ)": "Oil sands (in situ)",
    "Bakken / Three Forks": "Bakken",
}
_BC = {
    "Montney": "Montney", "Spirit River (Deep Basin)": "Spirit River / Deep Basin",
    "Dunlevy / Nikanassin": "Spirit River / Deep Basin", "Jean Marie (Redknife)": "Jean Marie",
    "Doig / Halfway": "Doig / Halfway", "Charlie Lake": "Charlie Lake / Baldonnel", "Baldonnel": "Charlie Lake / Baldonnel",
    "Horn River (Muskwa / Otter Park / Evie)": "Horn River", "Wabamun / Nisku / Leduc": "Devonian carbonates",
    "Mississippian (Midale / Frobisher)": "Mississippian (Debolt)", "Belly River": "Belly River",
}
_SK = {
    "Viking": "Viking", "Bakken / Three Forks": "Bakken / Three Forks",
    "Mississippian (Midale / Frobisher)": "Mississippian (Midale / Frobisher)",
    "Shaunavon / Upper Shaunavon": "Shaunavon", "Glauconitic / Mannville": "Mannville (heavy oil)",
    "Medicine Hat / Milk River (shallow gas)": "Shallow gas (Milk River)", "Belly River": "Belly River",
    "Oil sands (in situ)": "Mannville (heavy oil)",
}
_MB = [("Bakken / Three Forks", ["BAKKEN", "TORQUAY", "THREE FORKS"]), ("Amaranth", ["AMARANTH"]),
       ("Lodgepole", ["LODGEPOLE"]), ("Mission Canyon", ["MISSION CANYON"])]
_BY_PROV = {"AB": _AB, "BC": _BC, "SK": _SK}
CATEGORIES = {"AB": sorted(set(_AB.values())), "BC": sorted(set(_BC.values())), "SK": sorted(set(_SK.values())),
              "MB": [c for c, _ in _MB]}


def category(formation, province: str | None, target=None, status=None) -> str:
    """One of the province's recognised categories, or "Other".

    ``target`` (the licence's target formation) stands in when the pool is commingled or unknown; ``status``
    marks thermal oil-sands wells (steam-assisted, cyclic steam) whose pool isn't named."""
    prov = (province or "").upper()

    def one(f):
        if f is None or (isinstance(f, float) and f != f):
            return None
        s = str(f).strip().upper()
        if not s or s in ("NAN", "<NA>", "NONE"):
            return None
        if prov == "MB":
            for label, keys in _MB:
                if any(k in s for k in keys):
                    return label
            return OTHER
        p = play(f, prov)
        if p is None or p == COMMINGLED or "COMMINGLED" in s:
            return COMMINGLED
        return _BY_PROV.get(prov, {}).get(p, OTHER)

    c = one(formation)
    if c in (None, COMMINGLED):
        t = one(target)
        if t not in (None, COMMINGLED):
            return t
        if prov in ("AB", "SK") and status is not None and any(k in str(status).upper() for k in ("STEAM", "CYCLIC", "SAGD", "THERMAL")):
            return "Oil sands (in situ)" if prov == "AB" else "Mannville (heavy oil)"
        return OTHER
    return c
