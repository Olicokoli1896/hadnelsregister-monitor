"""Offline-Tests der Parser, der Branchenzuordnung und der Geo-Funktionen.

Ausführen:  python -m pytest -q   (oder: python -m unittest discover tests)
"""
import unittest

from hr_monitor.classify import Classifier
from hr_monitor.config import load_config
from hr_monitor.geo import get_geo, haversine, resolve_center
from hr_monitor.sources import bekanntmachungen, insolvenz, unternehmenssuche

BEK_LIST = """
<dl><dt class="ui-datalist-item"><span id="bekanntMachungenForm:datalistId:0:datumId">21.11.2026</span></dt><dd>
<a id="x" href="#" class="ui-commandlink ui-widget" onclick="fireBekanntmachung0('Sat Nov 21 00:00:00 CET 2026', '185209');;PrimeFaces.ab({});return false;"><label id="y" class="ui-outputlabel ui-widget">             Registerbekanntmachung nach dem Umwandlungsgesetz  <br>           Hessen Amtsgericht Kassel HRB 1234         <br> Muster Sanitär &amp; Heizung GmbH – Baunatal</label></a>
<a id="x2" href="#" class="ui-commandlink ui-widget" onclick="fireBekanntmachung1('Sat Nov 21 00:00:00 CET 2026', '185210');;PrimeFaces.ab({});return false;"><label id="y2" class="ui-outputlabel ui-widget">  Löschungsankündigung <br> Berlin Amtsgericht Berlin (Charlottenburg) HRB 99 B <br> Foo GmbH – Berlin</label></a>
</dd></dl>
"""

SEARCH_ROW = """
<table><tr data-ri="0" class="ui-widget-content"><td><table><tbody>
<tr><td class="ui-panelgrid-cell fontTableNameSize">Hessen <span class="fontWeightBold">Amtsgericht Kassel HRB 17477</span></td></tr>
<tr><td><span class="marginLeft20">ACP GmbH</span></td>
<td class="ui-panelgrid-cell sitzSuchErgebnisse"><span class="verticalText">Niestetal</span></td>
<td><span class="verticalText">aktuell</span></td>
<td><a href="#" onclick="PrimeFaces.addSubmitParam('ergebnissForm',{'ergebnissForm:t:0:j:6:fade_':'ergebnissForm:t:0:j:6:fade_'}).submit('ergebnissForm');">SI</a></td></tr>
<tr><td><table><tr><td class="RegPortErg_HistorieZn"><span>1.) ACP Heizung und Sanitär UG (haftungsbeschränkt)</span></td>
<td class="RegPortErg_SitzStatus"><span>1.) Kassel</span></td></tr></table></td></tr>
</tbody></table></td></tr></table>
"""

SI_XML = """<?xml version="1.0"?><tns:nachricht.reg.0400003 xmlns:tns="http://www.xjustiz.de">
<tns:grunddaten><tns:verfahrensdaten><tns:instanzdaten><tns:verfahrensgegenstand><tns:gegenstand>Strukturierter Registerinhalt</tns:gegenstand></tns:verfahrensgegenstand></tns:instanzdaten>
<tns:beteiligung><tns:beteiligter><tns:auswahl_beteiligter><tns:organisation><tns:bezeichnung><tns:bezeichnung.aktuell>Muster Elektro GmbH</tns:bezeichnung.aktuell></tns:bezeichnung>
<tns:anschrift><tns:strasse>Hauptstr.</tns:strasse><tns:hausnummer>1</tns:hausnummer><tns:postleitzahl>34121</tns:postleitzahl><tns:ort>Kassel</tns:ort></tns:anschrift></tns:organisation></tns:auswahl_beteiligter></tns:beteiligter></tns:beteiligung>
<tns:beteiligung><tns:beteiligter><tns:auswahl_beteiligter><tns:natuerlichePerson><tns:vollerName><tns:vorname>Max</tns:vorname><tns:nachname>Muster</tns:nachname></tns:vollerName></tns:natuerlichePerson></tns:auswahl_beteiligter></tns:beteiligter></tns:beteiligung>
</tns:verfahrensdaten></tns:grunddaten>
<tns:fachdaten><tns:basisdatenRegister><tns:letzteEintragung>2026-06-08</tns:letzteEintragung><tns:anzahlEintragungen>1</tns:anzahlEintragungen></tns:basisdatenRegister>
<tns:gegenstand>Ausführung von Elektroinstallationen</tns:gegenstand><tns:stammkapital><tns:zahl>25000.00</tns:zahl><tns:waehrung><code>EUR</code></tns:waehrung></tns:stammkapital></tns:fachdaten>
</tns:nachricht.reg.0400003>""".encode("utf-8")

INS_TABLE = """<table><tr>
<td><span id="tbl_ergebnis:0:otx_datum">02.11.2026</span></td><td><span id="tbl_ergebnis:0:otx_azAkt">9 IN 908/26</span></td>
<td><span id="tbl_ergebnis:0:otx_Gericht">Kassel</span></td><td><span id="tbl_ergebnis:0:otx_schuldner">Elektro Muster GmbH</span></td>
<td><span id="tbl_ergebnis:0:otx_Sitz">Vellmar</span></td><td><span id="tbl_ergebnis:0:otx_register">Kassel, HRB 1</span></td></tr></table>"""


class ParserTests(unittest.TestCase):
    def test_bekanntmachungen_list(self):
        es = bekanntmachungen.parse_list(BEK_LIST)
        self.assertEqual(len(es), 2)
        e = es[0]
        self.assertEqual(e["datum"], "2026-11-21")
        self.assertEqual(e["typ"], "umwandlung")
        self.assertEqual(e["gericht"], "Kassel")
        self.assertEqual(e["register"], "HRB 1234")
        self.assertEqual(e["firma"], "Muster Sanitär & Heizung GmbH")
        self.assertEqual(e["ort"], "Baunatal")
        self.assertEqual(es[1]["typ"], "loeschungsankuendigung")
        self.assertEqual(es[1]["gericht"], "Berlin (Charlottenburg)")

    def test_search_results(self):
        rows, overflow = unternehmenssuche.parse_results(SEARCH_ROW)
        self.assertFalse(overflow)
        r = rows[0]
        self.assertEqual((r["gericht"], r["register"], r["firma"], r["sitz"], r["status"]),
                         ("Kassel", "HRB 17477", "ACP GmbH", "Niestetal", "aktuell"))
        self.assertEqual(r["historie"][0]["firma"], "ACP Heizung und Sanitär UG (haftungsbeschränkt)")
        self.assertTrue(r["_si_key"].startswith("ergebnissForm:"))

    def test_si(self):
        si = unternehmenssuche.parse_si(SI_XML)
        self.assertEqual(si["gegenstand"], "Ausführung von Elektroinstallationen")
        self.assertEqual(si["anzahl_eintragungen"], "1")
        self.assertEqual(si["plz"], "34121")
        self.assertEqual(si["strasse"], "Hauptstr. 1")
        self.assertEqual(si["kapital"], "25.000,00 EUR")
        self.assertEqual(si["vertretung"], "Max Muster")

    def test_insolvenz(self):
        rows = insolvenz.parse_results(INS_TABLE)
        self.assertEqual(rows[0]["firma"], "Elektro Muster GmbH")
        self.assertEqual(rows[0]["register"], "Kassel, HRB 1")


class ClassifierTests(unittest.TestCase):
    def setUp(self):
        self.c = Classifier(load_config()["branchen"])

    def test_classify(self):
        self.assertEqual(self.c.classify("Müller Sanitär- und Heizungstechnik GmbH"), ["SHK"])
        self.assertEqual(self.c.classify("Elektro Schmidt e.K."), ["Elektro"])
        self.assertEqual(self.c.classify("Aqua Therm Sanitär, Heizung Elektro GmbH"), ["SHK", "Elektro"])
        self.assertEqual(self.c.classify("ETG-Elektronik GmbH"), [])
        self.assertEqual(self.c.classify("Elektroinstallation und Elektronik Meier"), ["Elektro"])
        self.assertEqual(self.c.classify("Bäckerei Stuttgart GmbH"), [])
        self.assertEqual(self.c.classify("Foo GmbH", "Installation von Wärmepumpen"), ["SHK"])


class GeoTests(unittest.TestCase):
    def test_radius(self):
        g = get_geo()
        lat, lon, land = resolve_center(g, "Kassel")
        self.assertEqual(land, "HE")
        self.assertLess(g.distance(lat, lon, ort="Baunatal"), 15)
        self.assertGreater(g.distance(lat, lon, ort="München"), 300)
        self.assertLess(g.distance(lat, lon, plz="34225"), 15)
        self.assertAlmostEqual(haversine(0, 0, 0, 1), 111.19, places=1)

    def test_ambiguous_name_prefers_nearest(self):
        g = get_geo()
        lat, lon, _ = resolve_center(g, "Kassel")
        # "Neustadt" gibt es oft – der nächstgelegene Treffer zählt
        d = g.distance(lat, lon, ort="Neustadt")
        self.assertIsNotNone(d)


if __name__ == "__main__":
    unittest.main()
