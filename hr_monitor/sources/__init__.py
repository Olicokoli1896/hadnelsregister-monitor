"""Datenquellen."""
from dataclasses import dataclass

from ..classify import Classifier
from ..config import Config
from ..geo import Geo, haversine
from ..store import Store


@dataclass
class Context:
    config: Config
    store: Store
    geo: Geo
    classifier: Classifier

    def regions_for(self, ort: str | None = None, plz: str | None = None):
        """Liefert [(region, entfernung_km)] für alle Regionen, in deren Radius der Ort liegt."""
        hits = []
        for reg in self.config.regionen:
            loc = self.geo.locate(ort, plz, near=(reg.lat, reg.lon))
            if not loc:
                continue
            d = haversine(reg.lat, reg.lon, loc[0], loc[1])
            if d <= reg.radius_km:
                hits.append((reg, round(d, 1)))
        return hits
