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

    def regions_for(self, ort: str | None = None, plz: str | None = None,
                    gericht: str | None = None):
        """Liefert [(region, entfernung_km)] für alle Regionen, in deren Radius der Ort liegt.

        Mehrdeutige Ortsnamen (z. B. "Marl", "Neustadt") werden über den Standort des
        zuständigen Gerichts aufgelöst: gewählt wird der Ort, der dem Gericht am nächsten liegt.
        """
        loc = None
        if not plz and gericht:
            g = self.geo.locate(ort=gericht)
            if g:
                loc = self.geo.locate(ort, near=(g[0], g[1]))
        hits = []
        for reg in self.config.regionen:
            l = loc or self.geo.locate(ort, plz, near=(reg.lat, reg.lon))
            if not l:
                continue
            d = haversine(reg.lat, reg.lon, l[0], l[1])
            if d <= reg.radius_km:
                hits.append((reg, round(d, 1)))
        return hits
