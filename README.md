# Handelsregister-Monitor SHK & Elektro

Überwacht automatisch Handelsregister- und Insolvenzveröffentlichungen von **SHK- und
Elektrobetrieben** in frei wählbaren Regionen (Stadt + Radius). Ergebnis:

* eine **statische Website** (`docs/`) mit einer Übersichtsseite pro Region, Filter nach
  Ereignisart, Branche und Freitext, und allen Eckdaten zu jedem Eintrag,
* **E-Mails pro Region** an eigene Verteiler, wahlweise mit allen Einträgen im Text oder
  nur mit Zusammenfassung und Link auf die Übersichtsseite,
* **tägliche Aktualisierung** über GitHub Actions.

## Erfasste Ereignisse

| Ereignis | Quelle | Wie erkannt |
|---|---|---|
| Neugründung | handelsregister.de, Unternehmenssuche | neues Aktenzeichen mit nur einer Eintragung (laut strukturiertem Registerinhalt) |
| Neueintragung / Zuzug | Unternehmenssuche | neues Aktenzeichen im Gebiet mit mehreren Eintragungen |
| Umfirmierung | Unternehmenssuche | Firmenname eines bekannten Aktenzeichens hat sich geändert |
| Sitzverlegung | Unternehmenssuche | Sitz eines bekannten Aktenzeichens hat sich geändert |
| Statusänderung | Unternehmenssuche | z. B. „aktuell“ → „gelöscht“ |
| Umwandlung (Verschmelzung, Spaltung, Ausgliederung …) | Registerbekanntmachungen | amtliche Bekanntmachung |
| Löschungsankündigung | Registerbekanntmachungen | amtliche Bekanntmachung |
| Einreichung neuer Dokumente, sonstige Bekanntmachungen | Registerbekanntmachungen | amtliche Bekanntmachung |
| Insolvenz (Eröffnung, Sicherungsmaßnahmen, Abweisung mangels Masse, Entscheidungen) | insolvenzbekanntmachungen.de | amtliche Bekanntmachung |

Zu neuen und geänderten Firmen wird der **strukturierte Registerinhalt (SI)** abgerufen:
Anschrift, PLZ, Unternehmensgegenstand, Kapital, Datum des Gesellschaftsvertrags und
Vertretungsberechtigte. Namen von Personen werden nur angezeigt, wenn
`personen_namen_anzeigen: true` gesetzt ist.

### Branchenzuordnung

Ein Unternehmen gilt als SHK bzw. Elektro, wenn Firmenname, frühere Firmennamen oder
Unternehmensgegenstand einen der Begriffe aus `config.yaml` → `branchen` enthalten.
Ausschlussbegriffe (z. B. „Elektronik“) werden vorher aus dem Text entfernt.

### Umkreis

Firmensitz bzw. PLZ werden offline über GeoNames-Daten (`data/geo_de.tsv`) in
Koordinaten umgerechnet und mit dem Radius um den Mittelpunkt der Region verglichen.

## Wichtige Einschränkungen

* **Seit August 2022 (DiRUG)** veröffentlichen die Registergerichte Neueintragungen und
  Änderungen nicht mehr als Bekanntmachung. Die Eintragung selbst gilt als
  Veröffentlichung. Neugründungen und Umfirmierungen erkennt das Tool deshalb durch einen
  **Abgleich** der Suchergebnisse mit dem zuletzt gespeicherten Bestand. Der erste Lauf
  baut nur den Bestand auf; Ereignisse erscheinen ab dem zweiten Lauf.
* Die Unternehmenssuche findet nur Firmen, deren Name (oder früherer Name) einen der
  `suchbegriffe_register` enthält. Ein Betrieb namens „Müller GmbH“ mit Gegenstand
  „Elektroinstallation“ wird **nicht** als Neugründung erkannt. Bekanntmachungen und
  Insolvenzen zu solchen Firmen werden ebenfalls nur über den Namen gefunden.
* **Nutzungsbedingungen handelsregister.de: höchstens 60 Abrufe pro Stunde.** Das Tool
  wartet standardmäßig 62 Sekunden zwischen zwei Abrufen und macht höchstens 55 Abrufe
  pro Lauf. Reicht das nicht für alle Gerichte, setzt der nächste Lauf an der Stelle fort,
  an der der letzte aufgehört hat. Bei großen Regionen dauert ein kompletter Durchgang
  also mehrere Tage, oder Sie lassen den Workflow mehrmals täglich laufen (mit mindestens
  einer Stunde Abstand).
* Die Unternehmenssuche liefert höchstens 100 Treffer pro Anfrage. Bei mehr Treffern teilt
  das Tool die Anfrage automatisch weiter auf: zuerst nach Einzelbegriffen, dann nach HRA/HRB,
  dann nach Orten im Umkreis.
* Alle Angaben ohne Gewähr. Maßgeblich ist ausschließlich das amtliche Register.

## Einrichtung

### 1. Konfiguration anpassen

In `config.yaml`:

* `regionen`: Name, Mittelpunkt (Stadt oder PLZ), Radius, Empfänger und optional die
  Registergerichte. Ohne Angabe werden die Gerichte automatisch aus den
  Registerbekanntmachungen ermittelt. Mit `python -m hr_monitor orte` sehen Sie, welche
  Orte im Radius liegen.
* `branchen`, `suchbegriffe_register`, `suchbegriffe_insolvenz`: Begriffe nach Bedarf.
* `site_url`: Adresse der veröffentlichten Website (für die Links in den Mails).
* `email.modus`: `text` (alle Einträge in der Mail) oder `link` (Zusammenfassung + Link).

### 2. Lokal testen

```bash
pip install -r requirements.txt
python -m unittest discover tests                 # Offline-Tests
python -m hr_monitor run --no-mail                # Daten abrufen + Website in docs/ bauen
python -m hr_monitor mail --dry-run               # Mails als Dateien nach out/ schreiben
```

### 3. Automatisch über GitHub Actions

1. **E-Mail-Zugang als Secrets hinterlegen** (Repository → Settings → Secrets and
   variables → Actions): `SMTP_HOST`, `SMTP_PORT` (587 für STARTTLS oder 465 für SSL),
   `SMTP_USER`, `SMTP_PASSWORD`, `MAIL_FROM`. Die Empfänger erhalten die Mail in BCC.
2. **GitHub Pages aktivieren**: Settings → Pages → „Deploy from a branch“, Branch `main`,
   Ordner `/docs`.
3. Der Workflow `.github/workflows/update.yml` läuft täglich um 05:17 UTC und lässt sich
   unter „Actions“ auch manuell starten. Er speichert den Datenstand (`data/state/`) und die
   Website (`docs/`) im Repository.

> **Datenschutz:** Eine GitHub-Pages-Seite ist öffentlich erreichbar (Suchmaschinen werden
> per `noindex` ausgeschlossen). Die Registerdaten sind zwar öffentlich, Insolvenzdaten
> unterliegen aber Zweckbindung und Löschfristen. Das Tool zeigt daher standardmäßig nur
> Insolvenzen von Unternehmen mit Registereintrag, entfernt sie nach 180 Tagen und blendet
> Personennamen aus. Soll die Seite nicht öffentlich sein, eignet sich ein Hosting mit
> Zugangsschutz (z. B. Netlify/Cloudflare Pages mit Passwort oder ein eigener Webspace mit
> `.htaccess`) oder `email.modus: text` ganz ohne Website.

## Aufbau

```
config.yaml                     Regionen, Branchen, Suchbegriffe, Limits, E-Mail
hr_monitor/
  __main__.py                   Kommandozeile (run, site, mail, orte)
  sources/bekanntmachungen.py   Registerbekanntmachungen
  sources/unternehmenssuche.py  Neueintragungen/Umfirmierungen per Bestandsabgleich + SI
  sources/insolvenz.py          Insolvenzbekanntmachungen
  geo.py, classify.py           Umkreis und Branchenzuordnung
  store.py                      Datenstand (data/state/*.json)
  site.py, mailer.py            Website und E-Mails
templates/                      HTML-Vorlagen für Website und Mails
docs/                           generierte Website (GitHub Pages)
```
