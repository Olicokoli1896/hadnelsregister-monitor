"""Offline-Geokodierung deutscher Orte/PLZ (GeoNames) und Umkreisprüfung."""
from __future__ import annotations

import math
import re
from collections import defaultdict
from functools import lru_cache

from .config import ROOT

GEO_FILE = ROOT / "data" / "geo_de.tsv"


def haversine(lat1, lon1, lat2, lon2) -> float:
    r = 6371.0
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dp, dl = p2 - p1, math.radians(lon2 - lon1)
    a = math.sin(dp / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dl / 2) ** 2
    return 2 * r * math.asin(math.sqrt(a))


_ABBR = [
    (r"\bst\.\s*", "sankt "), (r"\ba\.\s*d\.\s*", "an der "), (r"\ba\.\s*", "am "),
    (r"\bi\.\s*", "im "), (r"\bv\.\s*d\.\s*", "vor der "), (r"\bb\.\s*", "bei "),
]


def norm_ort(name: str) -> str:
    s = (name or "").lower().strip()
    s = re.sub(r"\(.*?\)", " ", s)
    s = s.split(",")[0].split("/")[0]
    for pat, rep in _ABBR:
        s = re.sub(pat, rep, s)
    s = s.replace("ß", "ss").replace("-", " ")
    s = re.sub(r"[^a-zäöü0-9 ]+", " ", s)
    return re.sub(r"\s+", " ", s).strip()


class Geo:
    def __init__(self):
        self.by_name: dict[str, list[tuple]] = defaultdict(list)
        self.by_plz: dict[str, list[tuple]] = defaultdict(list)
        with open(GEO_FILE, encoding="utf-8") as f:
            for line in f:
                if line.startswith("#") or line.startswith("plz\t"):
                    continue
                plz, ort, land, lat, lon = line.rstrip("\n").split("\t")
                rec = (plz, ort, land, float(lat), float(lon))
                self.by_plz[plz].append(rec)
                key = norm_ort(ort)
                self.by_name[key].append(rec)
                # "Frankfurt am Main" auch unter "frankfurt" auffindbar machen
                first = key.split(" ")[0]
                if first != key:
                    self.by_name.setdefault("~" + first, []).append(rec)

    def candidates(self, ort: str | None = None, plz: str | None = None) -> list[tuple]:
        if plz and plz in self.by_plz:
            return self.by_plz[plz]
        if not ort:
            return []
        key = norm_ort(ort)
        if key in self.by_name:
            return self.by_name[key]
        # Ortsteile wie "Kassel-Wilhelmshöhe" -> "kassel"
        for part in (key.split(" ")[0], ):
            if part in self.by_name:
                return self.by_name[part]
            if "~" + part in self.by_name:
                return self.by_name["~" + part]
        return []

    def locate(self, ort: str | None = None, plz: str | None = None,
               near: tuple[float, float] | None = None):
        """Liefert (lat, lon, land) – bei Mehrdeutigkeit den Treffer nächst `near`."""
        cands = self.candidates(ort, plz)
        if not cands:
            return None
        if near:
            best = min(cands, key=lambda c: haversine(near[0], near[1], c[3], c[4]))
        else:
            best = cands[0]
        return best[3], best[4], best[2]

    def distance(self, lat, lon, ort=None, plz=None) -> float | None:
        loc = self.locate(ort, plz, near=(lat, lon))
        if not loc:
            return None
        return haversine(lat, lon, loc[0], loc[1])

    def places_within(self, lat, lon, radius_km) -> list[tuple]:
        """Alle Orte (eindeutige Namen) im Umkreis, sortiert nach Entfernung."""
        seen = {}
        for recs in self.by_plz.values():
            for plz, ort, land, la, lo in recs:
                d = haversine(lat, lon, la, lo)
                if d <= radius_km and (ort not in seen or d < seen[ort][0]):
                    seen[ort] = (d, land)
        return sorted(((o, d, l) for o, (d, l) in seen.items()), key=lambda x: x[1])


@lru_cache(maxsize=1)
def get_geo() -> Geo:
    return Geo()


def resolve_center(geo: Geo, mittelpunkt: str):
    m = mittelpunkt.strip()
    loc = geo.locate(plz=m) if re.fullmatch(r"\d{5}", m) else geo.locate(ort=m)
    if not loc:
        raise ValueError(f"Mittelpunkt '{mittelpunkt}' nicht gefunden (Stadtname oder PLZ angeben)")
    return loc
