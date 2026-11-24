# Handelsregister-Monitor SHK & Elektro

Überwacht automatisch Handelsregister- und Insolvenzveröffentlichungen von **SHK- und
Elektrobetrieben** in frei wählbaren Regionen (Stadt + Radius). Ergebnis:

* eine **statische Website** (`docs/`) mit einer Übersichtsseite pro Region, Filter nach
  Ereignisart, Branche und Freitext, und allen Eckdaten zu jedem Eintrag,
* **E-Mails pro Region** an eigene Verteiler, wahlweise mit allen Einträgen im Text oder
  nur mit Zusammenfassung und Link auf die Übersichtsseite,
* **Aktualisierung alle zwei Tage** über GitHub Actions.

Voreingestellte Regionen: **Hannover, Braunschweig, Göttingen, Halberstadt, Wolfsburg**,
jeweils 100 km Umkreis, jede mit eigenem Verteiler.

### E-Mail-Logik

* Jede Region bekommt ihre eigene Mail mit **allen aktuellen Einträgen**
  (Datum höchstens `email.max_alter_tage` = 30 Tage alt).
* **Bereits an eine Region verschickte Einträge kommen nie wieder vor.** Das Tool
  speichert pro Region die versendeten Einträge (`data/state/meta.json` → `mail_gesendet`).
  Ein Eintrag gilt erst nach erfolgreichem Versand als verschickt.
* **Keine neuen Einträge → keine Mail** für diese Region.
* Liegt ein Ort im Umkreis mehrerer Regionen, erhält jede dieser Regionen den Eintrag.

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
  wartet standardmäßig 62 Sekunden zwischen zwei Abrufen und macht höchstens 260 Abrufe
  pro Lauf (gut 4,5 Stunden). Für die fünf Regionen mit je 100 km kommen rund 30
  Registergerichte zusammen. Der erste vollständige Durchgang verteilt sich deshalb auf
  zwei bis drei Läufe; jeder Lauf setzt dort fort, wo der vorige aufgehört hat.
* Die Unternehmenssuche liefert höchstens 100 Treffer pro Anfrage. Bei mehr Treffern teilt
  das Tool die Anfrage automatisch weiter auf: zuerst nach Einzelbegriffen, dann nach HRA/HRB,
  dann nach Rechtsform, zuletzt nach Orten im Gerichtsbezirk.
* Mehrdeutige Ortsnamen (z. B. „Marl“, „Neustadt“) werden über den Standort des
  zuständigen Gerichts aufgelöst.
* Alle Angaben ohne Gewähr. Maßgeblich ist ausschließlich das amtliche Register.

## Einrichtung

### 1. Konfiguration anpassen

In `config.yaml`:

* `regionen`: Name, Mittelpunkt (Stadt oder PLZ), Radius und optional die
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

1. **E-Mail-Versand über Resend einrichten** (siehe nächster Abschnitt).
2. **GitHub Pages aktivieren**: Settings → Pages → „Deploy from a branch“, Branch `main`,
   Ordner `/docs`.
3. Der Workflow `.github/workflows/update.yml` läuft alle zwei Tage um 03:17 UTC (an
   ungeraden Kalendertagen) und lässt sich unter „Actions“ auch manuell starten. Er speichert den Datenstand (`data/state/`) und die
   Website (`docs/`) im Repository.

### 4. E-Mail-Versand über Resend

Die Mails werden über die API von [Resend](https://resend.com) verschickt. Fehlt der
API-Key, läuft alles andere normal weiter: Der Mailversand wird übersprungen, die Mails
landen nur als Datei im Lauf, und die Einträge bleiben offen, bis der Versand klappt.

**Schritt 1: Resend-Konto und API-Key**

1. Auf [resend.com](https://resend.com) ein kostenloses Konto anlegen. Die dabei
   verwendete E-Mail-Adresse ist wichtig (siehe unten).
2. Im Resend-Dashboard unter **API Keys** → **Create API Key** einen Schlüssel anlegen
   (Berechtigung „Sending access“ genügt). Er beginnt mit `re_` und wird nur einmal
   angezeigt.

**Schritt 2: Secrets im Repository hinterlegen**

Im Repository auf GitHub: **Settings** → **Secrets and variables** → **Actions** →
**New repository secret**.

| Secret | Inhalt | Pflicht |
|---|---|---|
| `RESEND_API_KEY` | der API-Key aus Schritt 1 (`re_…`) | ja |
| `MAIL_TO` | Ihre eigene Adresse, mehrere durch Komma getrennt. Bekommt die Mails aller Regionen. | ja |
| `MAIL_FROM` | Absender. Leer lassen = `onboarding@resend.dev` | nein |
| `EMPFAENGER_HANNOVER`, `EMPFAENGER_BRAUNSCHWEIG`, `EMPFAENGER_GOETTINGEN`, `EMPFAENGER_HALBERSTADT`, `EMPFAENGER_WOLFSBURG` | Verteiler je Region, mehrere Adressen durch Komma getrennt | erst mit eigener Domain |

**Ohne eigene Domain (Start):** Solange `MAIL_FROM` leer ist, verschickt das Tool über
Resends Test-Absender `onboarding@resend.dev`. Resend stellt darüber **nur an die
E-Mail-Adresse des eigenen Resend-Kontos** zu. Tragen Sie deshalb genau diese Adresse als
`MAIL_TO` ein. Die regionalen Verteiler werden in diesem Modus nicht beliefert, damit
Resend die Mail nicht ablehnt.

**Später mit eigener Domain:** Domain in Resend unter **Domains** → **Add Domain**
hinzufügen und die angezeigten DNS-Einträge (SPF, DKIM) beim Domain-Anbieter eintragen.
Sobald Resend die Domain als „Verified“ anzeigt, nur das Secret `MAIL_FROM` ändern, z. B.
auf `Handelsregister-Monitor <monitor@ihre-firma.de>`. Code und Workflow bleiben gleich.
Ab dann gehen die Mails an `MAIL_TO` und zusätzlich in BCC an die Verteiler
`EMPFAENGER_<REGION>` (die Empfänger sehen sich gegenseitig nicht). Neue Regionen brauchen
einen Eintrag im Workflow (`.github/workflows/update.yml`, Abschnitt `env`).

**Schritt 3: Testen**

Unter **Actions** → **Handelsregister-Update** → **Run workflow** einen Lauf starten. Im
Log steht pro Region „Mail … über Resend gesendet“ oder der Grund, warum nichts verschickt
wurde. Gibt es keine neuen Einträge, wird keine Mail verschickt. Versendete Mails sehen Sie
auch im Resend-Dashboard unter **Emails**.

> **Alternativ SMTP:** Ist kein `RESEND_API_KEY` gesetzt, aber `SMTP_HOST`, verschickt das
> Tool per SMTP (`SMTP_HOST`, `SMTP_PORT`, `SMTP_USER`, `SMTP_PASSWORD`, `MAIL_FROM`).

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
