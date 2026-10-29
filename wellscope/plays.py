"""Group pool and formation names into the plays analysts talk about (Montney, Duvernay, Clearwater, Bakken...).

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
    for label, keys in PLAYS:
        if any(k in s for k in keys):
            return label
    if s.isdigit():                       # an unresolved code (BC formation codes), keep it recognisable
        return f"Formation code {s}"
    s = re.sub(r"[\(\[].*?[\)\]]", "", s)
    s = re.sub(r"\b(UNDEFINED|UNDEF|POOL|[A-Z]{1,2}\d*|\d+)\b$", "", s).strip(" -")
    return s.title() or None
