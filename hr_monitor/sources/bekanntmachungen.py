"""Registerbekanntmachungen von handelsregister.de.

Seit August 2022 (DiRUG) erscheinen hier nur noch bestimmte Bekanntmachungen:
Umwandlungen, Löschungsankündigungen, neu eingereichte Dokumente und Sonstiges.
Neueintragungen und Änderungen werden über die Unternehmenssuche erkannt.
"""
from __future__ import annotations

import html
import logging
import re
from datetime import datetime

from bs4 import BeautifulSoup

from ..net import BudgetExceeded, Session, Throttle
from ..store import event_id
from . import Context

log = logging.getLogger(__name__)

BASE = "https://www.handelsregister.de"
LIST_URL = BASE + "/rp_web/bekanntmachungen/welcome.xhtml"
DETAIL_URL = BASE + "/rp_web/einzelBekanntmachung/welcome.xhtml"

TYPE_MAP = {
    "umwandlungsgesetz": "umwandlung",
    "löschungsankündigung": "loeschungsankuendigung",
    "einreichung neuer dokumente": "neue_dokumente",
}

COURT_RE = re.compile(
    r"^(?P<land>.*?)\s*Amtsgericht\s+(?P<gericht>.+?)\s+(?P<art>HRA|HRB|GnR|PR|VR|GsR|PartR)\s+(?P<nr>.+)$"
)


def _type(label: str) -> str:
    low = label.lower()
    for k, v in TYPE_MAP.items():
        if k in low:
            return v
    return "sonstige_bekanntmachung"


def _iso(d: str) -> str:
    try:
        return datetime.strptime(d.strip(), "%d.%m.%Y").date().isoformat()
    except ValueError:
        return d


def parse_list(page: str) -> list[dict]:
    """Zerlegt die Listenansicht in einzelne Einträge."""
    entries = []
    current_date = None
    token = re.compile(
        r'datumId">(?P<datum>[\d.]+)<'
        r"|fireBekanntmachung\d+\('(?P<jsdate>[^']+)', '(?P<id>\d+)'\).*?"
        r'class="ui-outputlabel ui-widget">(?P<label>.*?)</label>',
        re.S,
    )
    for m in token.finditer(page):
        if m.group("datum"):
            current_date = _iso(m.group("datum"))
            continue
        parts = [html.unescape(re.sub(r"<[^>]+>", "", p)).strip()
                 for p in m.group("label").split("<br>")]
        if len(parts) < 3:
            continue
        art_label, court_part, name_part = parts[0], parts[1], parts[2]
        cm = COURT_RE.match(court_part)
        name, _, ort = name_part.rpartition(" – ")
        if not name:
            name, ort = name_part, ""
        entries.append({
            "datum": current_date,
            "js_datum": m.group("jsdate"),
            "rb_id": m.group("id"),
            "art_label": art_label,
            "typ": _type(art_label),
            "land": cm.group("land").strip() if cm else "",
            "gericht": cm.group("gericht").strip() if cm else "",
            "register": f'{cm.group("art")} {cm.group("nr").strip()}' if cm else court_part,
            "firma": name.strip(),
            "ort": ort.strip(),
        })
    return entries


def parse_detail(page: str) -> dict:
    sp = BeautifulSoup(page, "lxml")
    root = sp.find(id="contentID") or sp
    lines = [l.strip() for l in root.get_text("\n").split("\n") if l.strip()]
    info = {"volltext": ""}
    for i, l in enumerate(lines):
        if l.startswith("(Eintragungsdatum)") and i:
            info["eintragungsdatum"] = _iso(lines[i - 1])
    # Der Bekanntmachungstext ist der längste Absatz
    if lines:
        info["volltext"] = max(lines, key=len) if max(len(x) for x in lines) > 80 else ""
    for art in ("Verschmelzung", "Ausgliederung", "Abspaltung", "Aufspaltung", "Formwechsel",
                "Vermögensübertragung"):
        if art.lower() in info["volltext"].lower():
            info["unterart"] = art
            break
    for l in lines:
        if any(k in l for k in ("Gesellschaft mit beschränkter Haftung", "Kommanditgesellschaft",
                                "Aktiengesellschaft", "Unternehmergesellschaft", "eingetragener Kaufmann",
                                "Offene Handelsgesellschaft", "Genossenschaft")) and len(l) < 80:
            info["rechtsform"] = l
            break
    return info


class Bekanntmachungen:
    def __init__(self, ctx: Context, throttle: Throttle):
        self.ctx = ctx
        self.http = Session(throttle)

    def fetch_list(self) -> tuple[str, list[dict]]:
        r = self.http.get(LIST_URL)
        r.raise_for_status()
        return r.text, parse_list(r.text)

    def fetch_detail(self, page: str, entry: dict) -> dict:
        vs = re.search(r'name="javax.faces.ViewState"[^>]*value="([^"]+)"', page).group(1)
        src = re.search(r'remoteBekanntmachung = function\(\) \{PrimeFaces.ab\(\{s:"([^"]+)"', page).group(1)
        data = {
            "javax.faces.partial.ajax": "true", "javax.faces.source": src,
            "javax.faces.partial.execute": "bekanntMachungenForm",
            "javax.faces.partial.render": "bekanntMachungenForm", src: src,
            "datum": entry["js_datum"], "id": entry["rb_id"],
            "bekanntMachungenForm": "bekanntMachungenForm", "javax.faces.ViewState": vs,
        }
        self.http.post(LIST_URL, data=data, headers={"Faces-Request": "partial/ajax",
                                                     "X-Requested-With": "XMLHttpRequest"})
        r = self.http.get(DETAIL_URL)
        return parse_detail(r.text)

    def learn_courts(self, entries: list[dict]):
        """Merkt sich, welche Orte zu welchem Registergericht gehören."""
        m = self.ctx.store.meta.setdefault("gericht_orte", {})
        for e in entries:
            if e["gericht"] and e["ort"]:
                lst = m.setdefault(e["gericht"], [])
                if e["ort"] not in lst:
                    lst.append(e["ort"])

    def run(self) -> int:
        ctx = self.ctx
        page, entries = self.fetch_list()
        log.info("Registerbekanntmachungen: %d Einträge in der Liste", len(entries))
        self.learn_courts(entries)
        new = 0
        max_details = int(ctx.config.section("handelsregister").get("max_bekanntmachungen_details", 40))
        details_done = 0
        for e in entries:
            eid = event_id("rb", e["datum"], e["rb_id"])
            if ctx.store.has_event(eid):
                continue
            branchen = ctx.classifier.classify(e["firma"])
            if not branchen:
                continue
            regions = ctx.regions_for(ort=e["ort"], gericht=e["gericht"])
            if not regions:
                continue
            if details_done >= max_details:
                # Rest beim nächsten Lauf (die Liste reicht 8 Wochen zurück)
                log.info("Detail-Limit erreicht – weitere Treffer folgen im nächsten Lauf")
                break
            details_done += 1
            details = {}
            try:
                details = self.fetch_detail(page, e)
            except BudgetExceeded:
                raise
            except Exception as exc:  # Details sind optional
                log.warning("Details zu %s nicht abrufbar: %s", e["firma"], exc)
            ev = {
                "id": eid, "quelle": "Registerbekanntmachung", "typ": e["typ"],
                "datum": e["datum"], "firma": e["firma"], "ort": e["ort"],
                "gericht": e["gericht"], "register": e["register"], "land": e["land"],
                "branchen": branchen, "regionen": [r.slug for r, _ in regions],
                "entfernung_km": min(d for _, d in regions),
                "titel": e["art_label"],
                "text": details.get("volltext", ""),
                "rechtsform": details.get("rechtsform", ""),
                "eintragungsdatum": details.get("eintragungsdatum", ""),
                "unterart": details.get("unterart", ""),
                "link": LIST_URL,
            }
            if ctx.store.add_event(ev):
                new += 1
        return new
