"""Persistenter Zustand als JSON-Dateien im Repository (data/state)."""
from __future__ import annotations

import hashlib
import json
from datetime import date, datetime, timedelta
from pathlib import Path

from .config import ROOT

STATE_DIR = ROOT / "data" / "state"

# Anzeigenamen der Ereignisarten
EVENT_TYPES = {
    "neugruendung": "Neugründung",
    "neueintragung": "Neueintragung / Zuzug",
    "umfirmierung": "Umfirmierung",
    "sitzverlegung": "Sitzverlegung",
    "statusaenderung": "Statusänderung",
    "umwandlung": "Umwandlung",
    "loeschungsankuendigung": "Löschungsankündigung",
    "neue_dokumente": "Einreichung neuer Dokumente",
    "sonstige_bekanntmachung": "Sonstige Registerbekanntmachung",
    "insolvenz_eroeffnung": "Insolvenz: Eröffnung",
    "insolvenz_sicherung": "Insolvenz: Sicherungsmaßnahmen",
    "insolvenz_abweisung": "Insolvenz: Abweisung mangels Masse",
    "insolvenz_entscheidung": "Insolvenz: Entscheidung im Verfahren",
    "insolvenz_sonstige": "Insolvenz: Sonstiges",
}


def _load(path: Path, default):
    if path.exists():
        return json.loads(path.read_text(encoding="utf-8"))
    return default


def _dump(path: Path, data):
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".tmp")
    tmp.write_text(json.dumps(data, ensure_ascii=False, indent=1, sort_keys=True), encoding="utf-8")
    tmp.replace(path)


def event_id(*parts) -> str:
    return hashlib.sha1("|".join(str(p) for p in parts).encode()).hexdigest()[:16]


class Store:
    def __init__(self, state_dir: Path = STATE_DIR):
        self.dir = state_dir
        self.events: dict[str, dict] = _load(state_dir / "events.json", {})
        # bekannte Unternehmen aus der Unternehmenssuche, Schlüssel "Gericht|HRB 123"
        self.companies: dict[str, dict] = _load(state_dir / "companies.json", {})
        self.meta: dict = _load(state_dir / "meta.json", {})
        self.new_ids: list[str] = []

    # -- Ereignisse ---------------------------------------------------------
    def add_event(self, ev: dict) -> bool:
        """Speichert ein Ereignis. True, wenn es neu ist."""
        eid = ev["id"]
        if eid in self.events:
            old = self.events[eid]
            # Regionen zusammenführen, Details ergänzen
            old["regionen"] = sorted(set(old.get("regionen", [])) | set(ev.get("regionen", [])))
            for k, v in ev.items():
                if v and not old.get(k):
                    old[k] = v
            return False
        ev.setdefault("erfasst_am", datetime.now().isoformat(timespec="seconds"))
        self.events[eid] = ev
        self.new_ids.append(eid)
        return True

    def has_event(self, eid: str) -> bool:
        return eid in self.events

    def events_since(self, iso_ts: str | None, region_slug: str | None = None) -> list[dict]:
        res = []
        for ev in self.events.values():
            if region_slug and region_slug not in ev.get("regionen", []):
                continue
            if iso_ts and ev.get("erfasst_am", "") <= iso_ts:
                continue
            res.append(ev)
        return sorted(res, key=lambda e: (e.get("datum") or "", e.get("erfasst_am")), reverse=True)

    def prune(self, insolvenz_tage: int):
        """Entfernt Insolvenzdaten nach Ablauf der Aufbewahrungsfrist."""
        limit = (date.today() - timedelta(days=insolvenz_tage)).isoformat()
        for eid in [k for k, e in self.events.items()
                    if e["typ"].startswith("insolvenz") and (e.get("datum") or "") < limit]:
            del self.events[eid]
        # Versandprotokoll auf noch vorhandene Ereignisse beschränken
        for slug, ids in self.meta.get("mail_gesendet", {}).items():
            self.meta["mail_gesendet"][slug] = [i for i in ids if i in self.events]

    # -- Speichern ------------------------------------------------------------
    def save(self):
        _dump(self.dir / "events.json", self.events)
        _dump(self.dir / "companies.json", self.companies)
        _dump(self.dir / "meta.json", self.meta)
