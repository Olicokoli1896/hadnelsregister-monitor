"""Erkennung von Neueintragungen, Umfirmierungen und Sitzverlegungen über die
erweiterte Unternehmenssuche von handelsregister.de.

Prinzip: Für jede Region werden die Registergerichte mit Branchen-Suchbegriffen
abgefragt. Die Treffer werden mit dem gespeicherten Bestand verglichen:
  * neues Aktenzeichen          -> Neugründung (nur eine Eintragung) oder Neueintragung/Zuzug
  * geänderter Firmenname       -> Umfirmierung
  * geänderter Sitz             -> Sitzverlegung
  * geänderter Status           -> Statusänderung
Die Suche liefert max. 100 Treffer; bei Überlauf wird die Anfrage automatisch
weiter aufgeteilt (Einzelbegriffe -> HRA/HRB -> Orte im Umkreis).
Beim allerersten Durchlauf einer Anfrage wird nur der Bestand aufgebaut.
"""
from __future__ import annotations

import logging
import re
from datetime import date

from bs4 import BeautifulSoup
from lxml import etree

from ..net import BudgetExceeded, Session, Throttle
from ..store import event_id
from . import Context

log = logging.getLogger(__name__)

BASE = "https://www.handelsregister.de"
SEARCH_URL = BASE + "/rp_web/erweitertesuche/welcome.xhtml"
MAX_HITS = 100
MAX_WORDS = 5
# Rechtsform-Codes des Suchformulars (nur bei mehr als 100 Treffern genutzt)
RECHTSFORMEN = {
    "HRB": ("8", "1", "16"),               # GmbH inkl. UG, AG, ausländische Rechtsform
    "HRA": ("10", "12", "55", "5", "4"),   # KG, OHG, e.K. (verschiedene Codes)
}

REG_RE = re.compile(r"Amtsgericht\s+(?P<gericht>.+?)\s+(?P<reg>(?:HRA|HRB|GnR|PR|VR|GsR|PartR)\s+\S+(?:\s+\S+)?)$")


def parse_results(page: str) -> tuple[list[dict], bool]:
    sp = BeautifulSoup(page, "lxml")
    overflow = "maximale Trefferanzahl" in page
    rows = []
    for i, tr in enumerate(sp.select("tr[data-ri]")):
        head = tr.select_one("span.fontWeightBold")
        if not head:
            continue
        m = REG_RE.search(head.get_text(" ", strip=True))
        if not m:
            continue
        land = head.parent.get_text(" ", strip=True).replace(head.get_text(" ", strip=True), "").strip()
        name = tr.select_one("span.marginLeft20")
        sitz = tr.select_one("td.sitzSuchErgebnisse")
        verts = [v.get_text(strip=True) for v in tr.select("span.verticalText")]
        hist_names = [re.sub(r"^\d+\.\)\s*", "", s.get_text(strip=True))
                      for s in tr.select("td.RegPortErg_HistorieZn span")]
        hist_sitz = [re.sub(r"^\d+\.\)\s*", "", s.get_text(strip=True))
                     for s in tr.select("td.RegPortErg_SitzStatus span")]
        si_key = None
        for a in tr.find_all("a"):
            if a.get_text(strip=True) == "SI":
                km = re.search(r"addSubmitParam\('ergebnissForm',\{'([^']+)'", a.get("onclick", ""))
                si_key = km.group(1) if km else None
        rows.append({
            "index": i,
            "land": land,
            "gericht": m.group("gericht"),
            "register": m.group("reg"),
            "firma": name.get_text(" ", strip=True) if name else "",
            "sitz": sitz.get_text(" ", strip=True) if sitz else "",
            "status": verts[1] if len(verts) > 1 else "",
            "historie": [{"firma": n, "sitz": s} for n, s in zip(hist_names, hist_sitz)],
            "_si_key": si_key,
        })
    return rows, overflow


def _txt(el, path, ns):
    r = el.find(path, ns)
    return r.text.strip() if r is not None and r.text else ""


def parse_si(xml: bytes) -> dict:
    """Wertet den strukturierten Registerinhalt (XJustiz) aus."""
    info: dict = {}
    try:
        root = etree.fromstring(xml)
    except etree.XMLSyntaxError:
        return info
    ns = {"t": "http://www.xjustiz.de"}

    def first(local):
        r = root.find(f".//t:{local}", ns)
        return r.text.strip() if r is not None and r.text else ""

    info["gegenstand"] = first("gegenstand") if first("gegenstand") != "Strukturierter Registerinhalt" else ""
    for g in root.iter("{http://www.xjustiz.de}gegenstand"):
        if g.text and g.text.strip() != "Strukturierter Registerinhalt":
            info["gegenstand"] = g.text.strip()
    info["letzte_eintragung"] = first("letzteEintragung")
    info["anzahl_eintragungen"] = first("anzahlEintragungen")
    info["satzungsdatum"] = first("satzungsdatum")
    zahl = root.find(".//t:zahl", ns)
    if zahl is not None and zahl.text:
        cur = zahl.getnext()
        info["kapital"] = f"{float(zahl.text):,.2f}".replace(",", "X").replace(".", ",").replace("X", ".") + \
            (" " + cur.findtext("code") if cur is not None and cur.findtext("code") else " EUR")
    # Anschrift des Rechtsträgers (erste Organisation)
    org = root.find(".//t:beteiligter/t:auswahl_beteiligter/t:organisation", ns)
    if org is not None:
        an = org.find(".//t:anschrift", ns)
        if an is not None:
            info["strasse"] = (_txt(an, "t:strasse", ns) + " " + _txt(an, "t:hausnummer", ns)).strip()
            info["plz"] = _txt(an, "t:postleitzahl", ns)
            info["anschrift_ort"] = _txt(an, "t:ort", ns)
    # Vertretungsberechtigte (natürliche Personen) – nur Name, kein Geburtsdatum
    personen = []
    for p in root.iter("{http://www.xjustiz.de}natuerlichePerson"):
        vn = p.findtext(".//t:vorname", default="", namespaces=ns)
        nn = p.findtext(".//t:nachname", default="", namespaces=ns)
        if nn:
            personen.append(f"{vn} {nn}".strip())
    if personen:
        info["vertretung"] = ", ".join(dict.fromkeys(personen))
    return info


class SearchSession:
    """Eine Suchsitzung; erlaubt anschließend den Abruf von SI-Dokumenten der Trefferliste."""

    def __init__(self, throttle: Throttle):
        self.http = Session(throttle)
        self.page = ""
        self.result_url = ""

    def search(self, *, schlagwoerter: str, option: str = "2", gericht_code: str = "",
               register_art: str = "", sitz: str = "", rechtsform: str = "") -> tuple[list[dict], bool]:
        r = self.http.get(SEARCH_URL)
        vs = re.search(r'name="javax.faces.ViewState"[^>]*value="([^"]+)"', r.text).group(1)
        data = {
            "form": "form", "suchTyp": "e", "form:schlagwoerter": schlagwoerter,
            "form:schlagwortOptionen": option, "form:NiederlassungSitz": sitz,
            "form:registerArt_input": register_art, "form:registerNummer": "",
            "form:registergericht_input": gericht_code, "form:rechtsform_input": rechtsform,
            "form:staat_input": "", "form:postleitzahl": "", "form:ort": "", "form:strasse": "",
            "form:ergebnisseProSeite_input": "100", "form:btnSuche": "", "javax.faces.ViewState": vs,
        }
        r = self.http.post(SEARCH_URL, data=data)
        if "/error/" in r.url:
            raise RuntimeError(f"Suche fehlgeschlagen ({r.url})")
        if "sucheErgebnisse" not in r.url:
            msgs = re.findall(r'class="ui-messages-[a-z]+-(?:summary|detail)">([^<]+)', r.text)
            if any("kein" in m.lower() and "treffer" in m.lower() for m in msgs):
                self.page, self.result_url = r.text, r.url
                return [], False
            raise RuntimeError("Suche abgelehnt: " + ("; ".join(msgs) or r.url))
        self.page, self.result_url = r.text, r.url
        return parse_results(r.text)

    def fetch_si(self, row: dict) -> dict:
        if not row.get("_si_key"):
            return {}
        sp = BeautifulSoup(self.page, "lxml")
        f = sp.find("form", id="ergebnissForm")
        data = {i["name"]: i.get("value", "") for i in f.find_all("input")
                if i.get("name") and i.get("type") == "hidden"}
        data[row["_si_key"]] = row["_si_key"]
        r = self.http.post(BASE + f["action"], data=data)
        if b"xjustiz" not in r.content[:2000]:
            return {}
        return parse_si(r.content)


def court_codes(throttle: Throttle) -> dict[str, str]:
    """Name des Registergerichts -> interner Code (aus dem Suchformular)."""
    http = Session(throttle)
    page = http.get(SEARCH_URL).text
    sel = re.search(r'name="form:registergericht_input".*?</select>', page, re.S).group(0)
    return {name: code for code, name in re.findall(r'<option value="([A-Z0-9]+)"[^>]*>([^<]+)</option>', sel)}


class Unternehmenssuche:
    def __init__(self, ctx: Context, throttle: Throttle):
        self.ctx = ctx
        self.throttle = throttle

    # -- Planung der Anfragen ------------------------------------------------
    def courts_for_region(self, reg) -> list[str]:
        if reg.registergerichte:
            return reg.registergerichte
        # automatisch: Gerichte, deren bekannte Orte im Radius liegen
        result = []
        for gericht, orte in self.ctx.store.meta.get("gericht_orte", {}).items():
            # Gerichte weit außerhalb ausschließen (mehrdeutige Ortsnamen wie "Neustadt")
            d_g = self.ctx.geo.distance(reg.lat, reg.lon, ort=gericht)
            if d_g is None or d_g > reg.radius_km + 60:
                continue
            for o in orte:
                d = self.ctx.geo.distance(reg.lat, reg.lon, ort=o)
                if d is not None and d <= reg.radius_km:
                    result.append(gericht)
                    break
        return sorted(result)

    def queries(self) -> list[dict]:
        begriffe = self.ctx.config.get("suchbegriffe_register") or []
        qs, seen = [], set()
        for reg in self.ctx.config.regionen:
            for g in self.courts_for_region(reg):
                key = (g, "")
                if key in seen:
                    continue
                seen.add(key)
                qs.append({"gericht": g, "begriffe": begriffe, "region": reg.slug})
        return qs

    # -- Ausführung ----------------------------------------------------------
    def run(self) -> int:
        ctx, meta = self.ctx, self.ctx.store.meta
        try:
            codes = meta.get("gericht_codes") or court_codes(self.throttle)
            meta["gericht_codes"] = codes
        except BudgetExceeded:
            return 0
        queries = self.queries()
        if not queries:
            log.warning("Unternehmenssuche: keine Registergerichte für die Regionen bekannt")
            return 0
        # Rotation: beim letzten Stand weitermachen, falls das Budget nicht reicht
        start = meta.get("suche_position", 0) % len(queries)
        order = queries[start:] + queries[:start]
        new = 0
        done = 0
        for q in order:
            code = codes.get(q["gericht"])
            if not code:
                log.warning("Registergericht '%s' unbekannt – Schreibweise prüfen", q["gericht"])
                done += 1
                continue
            try:
                new += self._run_query(code, q)
                ctx.store.save()  # Zwischenstand sichern
            except BudgetExceeded:
                log.info("Abruflimit erreicht – nächster Lauf setzt bei %s fort", q["gericht"])
                break
            except Exception as exc:
                log.warning("Suche %s fehlgeschlagen: %s", q["gericht"], exc)
            done += 1
        meta["suche_position"] = (start + done) % len(queries)
        return new

    def _run_query(self, code: str, q: dict) -> int:
        """Fragt ein Gericht ab und teilt bei mehr als 100 Treffern weiter auf."""
        begriffe = q["begriffe"]
        # Das Portal erlaubt max. 5 Schlagwörter je Suche
        plans = [{"schlagwoerter": " ".join(begriffe[i:i + 5]), "option": "2"}
                 for i in range(0, len(begriffe), 5)]
        new = 0
        while plans:
            p = plans.pop(0)
            sess = SearchSession(self.throttle)
            rows, overflow = sess.search(gericht_code=code, schlagwoerter=p["schlagwoerter"],
                                         option=p["option"], register_art=p.get("art", ""),
                                         sitz=p.get("sitz", ""), rechtsform=p.get("rechtsform", ""))
            log.info("Suche %s %s %s %s %s: %d Treffer%s", q["gericht"], p["schlagwoerter"][:40],
                     p.get("art", ""), p.get("rechtsform", ""), p.get("sitz", ""), len(rows),
                     " (Überlauf)" if overflow else "")
            if overflow or len(rows) >= MAX_HITS:
                sub = self._split(p, q)
                if sub:
                    plans[:0] = sub
                    continue
            qkey = "|".join([q["gericht"], p["schlagwoerter"], p.get("art", ""), p.get("rechtsform", ""), p.get("sitz", "")])
            new += self._diff(rows, sess, qkey)
        return new

    def _split(self, p: dict, q: dict) -> list[dict]:
        words = p["schlagwoerter"].split()
        if len(words) > 1:
            return [{**p, "schlagwoerter": w} for w in words]
        if not p.get("art"):
            return [{**p, "art": a} for a in ("HRA", "HRB")]
        if not p.get("rechtsform") and p["art"] in RECHTSFORMEN:
            return [{**p, "rechtsform": c} for c in RECHTSFORMEN[p["art"]]]
        if not p.get("sitz"):
            return [{**p, "sitz": o} for o in self._orte_fuer_gericht(q["gericht"])]
        return []  # nicht weiter teilbar – Ergebnis wird so übernommen

    def _orte_fuer_gericht(self, gericht: str) -> list[str]:
        """Orte im Bezirk des Gerichts (aus den Bekanntmachungen gelernt), die in einer Region liegen."""
        known = self.ctx.store.meta.get("gericht_orte", {}).get(gericht, [])
        orte = [o for o in known if self.ctx.regions_for(ort=o, gericht=gericht)]
        if not orte:
            g = self.ctx.geo.locate(ort=gericht)
            if g:
                orte = [o for o, _, _ in self.ctx.geo.places_within(g[0], g[1], 25)]
        return sorted(set(orte))[:60]

    def _diff(self, rows: list[dict], sess: SearchSession, qkey: str) -> int:
        ctx, store = self.ctx, self.ctx.store
        baselined = store.meta.setdefault("suche_baseline", [])
        is_baseline = qkey not in baselined
        new = 0
        today = date.today().isoformat()
        for row in rows:
            key = f'{row["gericht"]}|{row["register"]}'
            names = [row["firma"]] + [h["firma"] for h in row["historie"]]
            branchen = ctx.classifier.classify(*names)
            regions = ctx.regions_for(ort=row["sitz"], gericht=row["gericht"])
            old = store.companies.get(key)
            snapshot = {k: row[k] for k in ("gericht", "register", "firma", "sitz", "status", "land")}
            snapshot["zuletzt_gesehen"] = today
            events = []
            if old is None:
                # Branche wird bei neuen Firmen ggf. erst über den Gegenstand (SI) bestimmt
                if not is_baseline and regions:
                    events.append("neu")
            else:
                if old.get("firma") != row["firma"]:
                    events.append("umfirmierung")
                if old.get("sitz") != row["sitz"]:
                    events.append("sitzverlegung")
                if old.get("status") and old.get("status") != row["status"]:
                    events.append("statusaenderung")
            if old:
                snapshot = {**old, **snapshot}
            store.companies[key] = snapshot
            if not events or not regions:
                continue
            if events != ["neu"] and not (branchen or ctx.classifier.classify(snapshot.get("gegenstand"))):
                continue
            si = {}
            try:
                si = sess.fetch_si(row)
            except BudgetExceeded:
                raise
            except Exception as exc:
                log.warning("SI für %s nicht abrufbar: %s", row["firma"], exc)
            if si and not ctx.config.get("personen_namen_anzeigen"):
                si.pop("vertretung", None)
            if si:
                branchen = ctx.classifier.classify(*names, si.get("gegenstand")) or branchen
                if si.get("plz"):
                    regions = ctx.regions_for(ort=row["sitz"], plz=si["plz"]) or regions
                store.companies[key].update({k: si[k] for k in ("plz", "strasse", "gegenstand") if si.get(k)})
            if not branchen:
                continue
            for kind in events:
                if kind == "neu":
                    kind = "neugruendung" if si.get("anzahl_eintragungen") == "1" else "neueintragung"
                    titel = "Neugründung" if kind == "neugruendung" else "Neu im Register (Bereich)"
                    detail = ""
                elif kind == "umfirmierung":
                    titel, detail = "Umfirmierung", f'bisher: {old.get("firma")}'
                elif kind == "sitzverlegung":
                    titel, detail = "Sitzverlegung", f'bisher: {old.get("sitz")} → neu: {row["sitz"]}'
                else:
                    titel, detail = "Statusänderung", f'{old.get("status")} → {row["status"]}'
                ev = {
                    "id": event_id("us", key, kind, row["firma"], row["sitz"], row["status"]),
                    "quelle": "Unternehmenssuche", "typ": kind,
                    "datum": si.get("letzte_eintragung") or today,
                    "firma": row["firma"], "ort": row["sitz"], "gericht": row["gericht"],
                    "register": row["register"], "land": row["land"], "status": row["status"],
                    "branchen": branchen, "regionen": [r.slug for r, _ in regions],
                    "entfernung_km": min(d for _, d in regions), "titel": titel, "text": detail,
                    "historie": row["historie"], **{k: v for k, v in si.items() if v},
                    "link": "https://www.handelsregister.de/rp_web/erweitertesuche/welcome.xhtml",
                }
                if store.add_event(ev):
                    new += 1
        if is_baseline:
            baselined.append(qkey)
            log.info("Bestand für '%s' aufgebaut (%d Unternehmen)", qkey, len(rows))
        return new
