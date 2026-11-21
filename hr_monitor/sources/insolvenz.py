"""Insolvenzbekanntmachungen (neu.insolvenzbekanntmachungen.de)."""
from __future__ import annotations

import logging
import re
from datetime import date, datetime, timedelta

from bs4 import BeautifulSoup

from ..net import Session, Throttle
from ..store import event_id
from . import Context

log = logging.getLogger(__name__)

BASE = "https://neu.insolvenzbekanntmachungen.de"
SEARCH_URL = BASE + "/ap/suche.jsf"

GEGENSTAND_TYP = {
    "EROEFF": "insolvenz_eroeffnung",
    "SICHMASS": "insolvenz_sicherung",
    "ABWMASS": "insolvenz_abweisung",
    "ENT_VERF": "insolvenz_entscheidung",
}
F = "frm_suche:"


def parse_results(page: str) -> list[dict]:
    sp = BeautifulSoup(page, "lxml")
    rows = []
    for tr in sp.select("table tr"):
        cells = {}
        for span in tr.select("td span[id^=tbl_ergebnis]"):
            cells[span["id"].rsplit(":", 1)[-1]] = span.get_text(" ", strip=True)
        if "otx_schuldner" not in cells:
            continue
        rows.append({
            "datum": cells.get("otx_datum", ""), "aktenzeichen": cells.get("otx_azAkt", ""),
            "gericht": cells.get("otx_Gericht", ""),
            # Zusätze wie "vertr. d. d. GF Max Muster" enthalten Personennamen -> abschneiden
            "firma": re.sub(r"\s+vertr\..*$", "", cells.get("otx_schuldner", "")),
            "sitz": cells.get("otx_Sitz", ""), "register": cells.get("otx_register", ""),
        })
    return rows


class Insolvenz:
    def __init__(self, ctx: Context):
        self.ctx = ctx
        cfg = ctx.config.section("insolvenz")
        self.cfg = cfg
        self.http = Session(Throttle(cfg.get("sekunden_zwischen_abrufen", 4)))

    def bundeslaender(self) -> list[str]:
        laender = set()
        for reg in self.ctx.config.regionen:
            for _, _, land in self.ctx.geo.places_within(reg.lat, reg.lon, reg.radius_km):
                laender.add(land)
        return sorted(laender)

    def search(self, land: str, firma: str, gegenstand: str, von: date) -> list[dict]:
        r = self.http.get(SEARCH_URL)
        sp = BeautifulSoup(r.text, "lxml")
        form = sp.find("form", id="frm_suche")
        data = {}
        for el in form.find_all(["input", "select"]):
            n = el.get("name")
            if not n or el.get("type") in ("checkbox", "submit", "radio", "image"):
                continue
            if el.name == "select":
                o = el.find("option", selected=True) or el.find("option")
                data[n] = o.get("value", "") if o else ""
            else:
                data[n] = el.get("value", "")
        data.update({
            F + "lsom_bundesland:codelist:scl_bundesland:mysom": land,
            F + "litx_firmaNachName:text": firma,
            F + "ldi_datumVon:datumHtml5": von.isoformat(),
            F + "ldi_datumBis:datumHtml5": date.today().isoformat(),
            F + "lsom_gegenstand:codelist:mysom": gegenstand,
            F + "cbt_suchen": "Suchen",
        })
        r = self.http.post(BASE + form["action"], data=data)
        return parse_results(r.text)

    def classify_type(self, land: str, row: dict, von: date) -> str:
        """Ermittelt den Verfahrensabschnitt über gezielte Suchen nach dem Firmennamen."""
        for g in self.cfg.get("gegenstaende") or list(GEGENSTAND_TYP):
            try:
                hits = self.search(land, row["firma"] + "*", g, von)
            except Exception as exc:
                log.warning("Typbestimmung für %s fehlgeschlagen: %s", row["firma"], exc)
                return "insolvenz_sonstige"
            if any(h["aktenzeichen"] == row["aktenzeichen"] and h["datum"] == row["datum"] for h in hits):
                return GEGENSTAND_TYP.get(g, "insolvenz_sonstige")
        return "insolvenz_sonstige"

    def run(self) -> int:
        ctx = self.ctx
        tage = int(self.cfg.get("tage_rueckwirkend", 14))
        von = date.today() - timedelta(days=tage)
        nur_hr = self.cfg.get("nur_mit_registereintrag", True)
        begriffe = ctx.config.get("suchbegriffe_insolvenz") or []
        new = 0
        for land in self.bundeslaender():
            for b in begriffe:
                try:
                    rows = self.search(land, b, "NO_CODE", von)
                except Exception as exc:
                    log.warning("Insolvenzsuche %s/%s fehlgeschlagen: %s", land, b, exc)
                    continue
                log.info("Insolvenz %s %s: %d Treffer", land, b, len(rows))
                for row in rows:
                    if nur_hr and not re.search(r"\b(HRA|HRB|GnR|PR)\b", row["register"]):
                        continue
                    branchen = ctx.classifier.classify(row["firma"])
                    if not branchen:
                        continue
                    regions = ctx.regions_for(ort=row["sitz"])
                    if not regions:
                        continue
                    try:
                        d = datetime.strptime(row["datum"], "%d.%m.%Y").date().isoformat()
                    except ValueError:
                        d = row["datum"]
                    eid = event_id("ins", row["aktenzeichen"], row["gericht"], d, row["firma"])
                    if ctx.store.has_event(eid):
                        continue
                    typ = self.classify_type(land, row, von)
                    gericht, _, register = row["register"].partition(",")
                    ev = {
                        "id": eid, "quelle": "Insolvenzbekanntmachung", "typ": typ,
                        "datum": d, "firma": row["firma"], "ort": row["sitz"],
                        "gericht": gericht.strip(), "register": register.strip(),
                        "insolvenzgericht": row["gericht"], "aktenzeichen": row["aktenzeichen"],
                        "branchen": branchen, "regionen": [r.slug for r, _ in regions],
                        "entfernung_km": min(x for _, x in regions),
                        "titel": "Insolvenzbekanntmachung",
                        "text": f'Aktenzeichen {row["aktenzeichen"]}, Insolvenzgericht {row["gericht"]}',
                        "link": SEARCH_URL,
                    }
                    if ctx.store.add_event(ev):
                        new += 1
        return new
