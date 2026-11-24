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

1. **E-Mail-Versand über Gmail einrichten** (siehe nächster Abschnitt).
2. **Website bei Cloudflare Pages veröffentlichen** (siehe Abschnitt 5). GitHub Pages
   (Settings → Pages → Branch `main`, Ordner `/docs`) funktioniert weiterhin als Alternative.
3. Der Workflow `.github/workflows/update.yml` läuft alle zwei Tage um 03:17 UTC (an
   ungeraden Kalendertagen; 04:17 Uhr MEZ, 05:17 Uhr MESZ) und lässt sich unter „Actions“
   auch manuell starten. Er speichert den Datenstand (`data/state/`) und die Website
   (`docs/`) im Repository.

### 4. E-Mail-Versand über Gmail

Die Mails gehen per SMTP über ein Gmail-Konto raus (`smtp.gmail.com`, Port 587, STARTTLS).
Fehlen die Zugangsdaten, läuft alles andere normal weiter: Der Mailversand wird
übersprungen, und die Einträge bleiben offen, bis der Versand klappt.

**Schritt 1: App-Passwort erzeugen.** Im Google-Konto die Bestätigung in zwei Schritten
einschalten (myaccount.google.com → Sicherheit), dann unter
<https://myaccount.google.com/apppasswords> ein App-Passwort anlegen (16 Zeichen, wird nur
einmal angezeigt).

**Schritt 2: Secrets im Repository hinterlegen** (**Settings** → **Secrets and variables**
→ **Actions** → **New repository secret**):

| Secret | Inhalt | Pflicht |
|---|---|---|
| `SMTP_USER` | Gmail-Adresse, z. B. `name@gmail.com` | ja |
| `SMTP_PASSWORD` | das App-Passwort (Leerzeichen werden entfernt) | ja |
| `MAIL_TO` | Adresse(n), die alle Regionen bekommen, mehrere durch Komma | ja, wenn keine Verteiler |
| `EMPFAENGER_HANNOVER`, `EMPFAENGER_BRAUNSCHWEIG`, `EMPFAENGER_GOETTINGEN`, `EMPFAENGER_HALBERSTADT`, `EMPFAENGER_WOLFSBURG` | Verteiler je Region, mehrere Adressen durch Komma | nein |
| `MAIL_FROM` | z. B. `Handelsregister-Monitor <name@gmail.com>`; leer = `SMTP_USER` | nein |
| `SMTP_HOST`, `SMTP_PORT` | nur für einen anderen Server; leer = `smtp.gmail.com` / `587` | nein |

Alle Empfänger stehen im BCC und sehen sich gegenseitig nicht. Ein privates Gmail-Konto
verschickt rund 500 Empfänger pro Tag.

**Schritt 3: Testen.** Unter **Actions** → **Handelsregister-Update** → **Run workflow**
einen Lauf starten. Im Log steht pro Region „Mail an … Empfänger gesendet“ oder der Grund,
warum nichts verschickt wurde. Gibt es keine neuen Einträge, wird keine Mail verschickt.

> **Alternativ Resend:** Ist das Secret `RESEND_API_KEY` gesetzt, wird statt Gmail über die
> Resend-API verschickt (Absender `MAIL_FROM`, leer = `onboarding@resend.dev`, das nur an
> die Adresse des Resend-Kontos zustellt). Für Gmail dieses Secret also nicht anlegen.

### 5. Website bei Cloudflare Pages

1. Im Cloudflare-Dashboard **Workers & Pages** → **Create application** → Tab **Pages** →
   **Import an existing Git repository** → GitHub verbinden und dieses Repository wählen.
2. Einstellungen: Production branch `main`, Framework preset *None*, Build command
   `exit 0`, Build output directory `docs`. **Save and Deploy**.
3. Die Adresse (`https://<projektname>.pages.dev/`) als GitHub-Variable `SITE_URL`
   hinterlegen (**Settings** → **Secrets and variables** → **Actions** → Tab **Variables**).
   Sie steht dann in den Links der Mails; ohne Variable gilt `site_url` aus `config.yaml`.

Nach jedem Lauf pusht der Workflow nach `main`, Cloudflare veröffentlicht die Seite dann
automatisch neu. Zugangsschutz: Pages-Projekt → **Settings** → **Enable access policy**
(Cloudflare Access, kostenlos bis 50 Nutzer).

> **Datenschutz:** Eine GitHub-Pages-Seite ist öffentlich erreichbar (Suchmaschinen werden
> per `noindex` ausgeschlossen). Die Registerdaten sind zwar öffentlich, Insolvenzdaten
> unterliegen aber Zweckbindung und Löschfristen. Das Tool zeigt daher standardmäßig nur
> Insolvenzen von Unternehmen mit Registereintrag, entfernt sie nach 180 Tagen und blendet
> Personennamen aus. Soll die Seite nicht öffentlich sein, eignet sich ein Hosting mit
> Zugangsschutz (z. B. Cloudflare Pages mit Cloudflare Access oder ein eigener Webspace mit
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
docs/                           generierte Website (Cloudflare Pages / GitHub Pages)
```
