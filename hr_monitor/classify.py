"""Branchenzuordnung (SHK / Elektro) anhand von Firmenname und Gegenstand."""
from __future__ import annotations


class Classifier:
    def __init__(self, branchen: dict):
        self.rules = {}
        for name, spec in (branchen or {}).items():
            self.rules[name] = (
                [b.lower() for b in spec.get("begriffe", [])],
                [b.lower() for b in spec.get("ausschluss", [])],
            )

    def classify(self, *texts: str | None) -> list[str]:
        text = " ".join(t for t in texts if t).lower()
        result = []
        for name, (inc, exc) in self.rules.items():
            # Ausschlussbegriffe werden aus dem Text entfernt, bevor gesucht wird:
            # "Elektronik GmbH" -> kein Treffer, "Elektroinstallation und Elektronik" -> Treffer
            t = text
            for e in exc:
                t = t.replace(e, " ")
            if any(i in t for i in inc):
                result.append(name)
        return result
