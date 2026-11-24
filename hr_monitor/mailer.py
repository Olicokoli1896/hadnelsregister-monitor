"""Versand der regionalen E-Mail-Berichte über SMTP (z. B. Gmail) oder die Resend-API."""
from __future__ import annotations

import logging
import os
import smtplib
import ssl
from datetime import date, datetime, timedelta
from email.message import EmailMessage
from pathlib import Path

import requests

from .config import Config, Region
from .site import env
from .store import Store

log = logging.getLogger(__name__)

RESEND_URL = "https://api.resend.com/emails"
# Test-Absender von Resend: funktioniert ohne eigene Domain, stellt aber nur an die
# E-Mail-Adresse des Resend-Kontos zu.
RESEND_TESTABSENDER = "onboarding@resend.dev"
# Ist nur SMTP_USER gesetzt, wird über Gmail verschickt.
GMAIL_HOST = "smtp.gmail.com"


def _split(value: str | None) -> list[str]:
    return [a.strip() for a in (value or "").replace(";", ",").split(",") if a.strip()]


def mail_from() -> str:
    return (os.environ.get("MAIL_FROM") or "").strip() or RESEND_TESTABSENDER


def ist_testabsender(absender: str) -> bool:
    """True, wenn über die Resend-Testdomain (resend.dev) verschickt wird."""
    adresse = absender.rsplit("<", 1)[-1].rstrip(">").strip().lower()
    return adresse.endswith("@resend.dev")


def render(cfg: Config, region: Region, events: list[dict]) -> tuple[str, str, str]:
    mcfg = cfg.section("email")
    modus = mcfg.get("modus", "text")
    link = cfg.get("site_url", "").rstrip("/") + f"/{region.slug}.html"
    e = env()
    ctx = dict(cfg=cfg, region=region, events=events, modus=modus, link=link,
               stand=datetime.now().strftime("%d.%m.%Y"))
    html = e.get_template("email.html.j2").render(**ctx)
    text = e.get_template("email.txt.j2").render(**ctx)
    subject = mcfg.get("betreff", "Handelsregister-Update {region}").format(
        region=region.name, anzahl=len(events))
    return subject, html, text


def recipients(region: Region) -> list[str]:
    """Empfänger aus config.yaml, GitHub-Secret EMPFAENGER_<REGION> und MAIL_TO (alle Regionen)."""
    env_name = "EMPFAENGER_" + region.slug.upper().replace("-", "_")
    extra = _split(os.environ.get(env_name))
    return list(dict.fromkeys(list(region.empfaenger) + extra + _split(os.environ.get("MAIL_TO"))))


def resend_recipients(region: Region) -> tuple[list[str], list[str]]:
    """(to, bcc) für den Versand über Resend.

    Mit dem Test-Absender onboarding@resend.dev nimmt Resend nur die Adresse des
    Resend-Kontos an. Dann geht die Mail ausschließlich an MAIL_TO; die Verteiler der
    Regionen werden erst mit eigener, verifizierter Domain (MAIL_FROM) beliefert.
    """
    mail_to = _split(os.environ.get("MAIL_TO"))
    if ist_testabsender(mail_from()):
        return mail_to, []
    alle = recipients(region)
    to = mail_to or [mail_from()]
    return to, [a for a in alle if a not in to]


def send_resend(api_key: str, subject: str, html: str, text: str,
                to: list[str], bcc: list[str]) -> str:
    """Schickt eine Mail über die Resend-API und gibt die Resend-ID zurück."""
    payload = {"from": mail_from(), "to": to, "subject": subject, "html": html, "text": text}
    if bcc:
        payload["bcc"] = bcc
    r = requests.post(RESEND_URL, json=payload, timeout=60,
                      headers={"Authorization": f"Bearer {api_key}",
                               "User-Agent": "hr-monitor/1.0"})
    if r.status_code >= 400:
        raise RuntimeError(f"Resend-API antwortet {r.status_code}: {r.text[:300]}")
    return r.json().get("id", "")


def pending_events(cfg: Config, store: Store, region: Region) -> list[dict]:
    """Noch nicht an diese Region verschickte, aktuelle Einträge."""
    sent_ids = set(store.meta.get("mail_gesendet", {}).get(region.slug, []))
    max_alter = int(cfg.section("email").get("max_alter_tage", 30))
    limit = (date.today() - timedelta(days=max_alter)).isoformat()
    return [e for e in store.events_since(None, region.slug)
            if e["id"] not in sent_ids and (e.get("datum") or e.get("erfasst_am", "")) >= limit]


def _ablegen(outdir: Path | None, reg: Region, subject: str, html: str, text: str):
    if outdir:
        outdir.mkdir(parents=True, exist_ok=True)
        (outdir / f"mail-{reg.slug}.html").write_text(html, encoding="utf-8")
        (outdir / f"mail-{reg.slug}.txt").write_text(f"Betreff: {subject}\n\n{text}", encoding="utf-8")


def send(cfg: Config, store: Store, dry_run: bool = False, outdir: Path | None = None) -> int:
    mcfg = cfg.section("email")
    if not mcfg.get("aktiv", True):
        log.info("E-Mail-Versand deaktiviert")
        return 0
    sent_state = store.meta.setdefault("mail_gesendet", {})
    api_key = (os.environ.get("RESEND_API_KEY") or "").strip()
    host = smtp_host()
    if not dry_run:
        if api_key:
            log.info("Mailversand über Resend, Absender %s", mail_from())
            if ist_testabsender(mail_from()):
                log.info("Test-Absender aktiv: Mails gehen nur an MAIL_TO, "
                         "Verteiler der Regionen erst mit eigener Domain")
        elif host:
            log.info("Mailversand über SMTP (%s), Absender %s", host, smtp_from())
        else:
            log.warning("Weder SMTP_USER/SMTP_PASSWORD (Gmail) noch RESEND_API_KEY gesetzt – "
                        "Mailversand wird übersprungen, Mails werden nur als Datei abgelegt. "
                        "Einträge bleiben offen.")
    sent = 0
    for reg in cfg.regionen:
        events = pending_events(cfg, store, reg)
        if not events:
            log.info("Region %s: keine neuen Einträge – keine Mail", reg.name)
            continue
        subject, html, text = render(cfg, reg, events)
        if dry_run or not (api_key or host):
            _ablegen(outdir, reg, subject, html, text)
            continue
        if api_key:
            to, bcc = resend_recipients(reg)
            if not to:
                log.warning("Region %s: MAIL_TO nicht gesetzt – keine Mail", reg.name)
                _ablegen(outdir, reg, subject, html, text)
                continue
            try:
                mail_id = send_resend(api_key, subject, html, text, to, bcc)
            except Exception as exc:  # Netz- oder API-Fehler: nächste Region, Einträge bleiben offen
                log.error("Region %s: Versand über Resend fehlgeschlagen: %s", reg.name, exc)
                continue
            log.info("Mail %s an %d Empfänger (%s) über Resend gesendet: %d Einträge",
                     mail_id, len(to) + len(bcc), reg.name, len(events))
        else:
            empf = recipients(reg)
            if not empf:
                log.warning("Region %s: keine Empfänger hinterlegt – Mail wird nur als Datei abgelegt",
                            reg.name)
                _ablegen(outdir, reg, subject, html, text)
                continue
            try:
                _send_smtp(host, subject, html, text, empf)
            except Exception as exc:  # z. B. falsches App-Passwort: nächste Region, Einträge bleiben offen
                log.error("Region %s: Versand über SMTP (%s) fehlgeschlagen: %s", reg.name, host, exc)
                continue
            log.info("Mail an %d Empfänger (%s) gesendet: %d Einträge", len(empf), reg.name, len(events))
        # Erst nach erfolgreichem Versand als verschickt markieren
        sent_state.setdefault(reg.slug, []).extend(e["id"] for e in events)
        sent += 1
    return sent


def smtp_host() -> str:
    """SMTP-Server: SMTP_HOST, sonst smtp.gmail.com, sobald SMTP_USER gesetzt ist."""
    host = (os.environ.get("SMTP_HOST") or "").strip()
    if not host and (os.environ.get("SMTP_USER") or "").strip():
        host = GMAIL_HOST
    return host


def smtp_from() -> str:
    return (os.environ.get("MAIL_FROM") or "").strip() or (os.environ.get("SMTP_USER") or "").strip()


def _send_smtp(host: str, subject: str, html: str, text: str, empf: list[str]):
    msg = EmailMessage()
    msg["Subject"] = subject
    msg["From"] = smtp_from()
    msg["To"] = msg["From"]  # Empfänger im BCC, damit sie sich gegenseitig nicht sehen
    msg.set_content(text)
    msg.add_alternative(html, subtype="html")
    port = int(os.environ.get("SMTP_PORT") or "587")
    ctx = ssl.create_default_context()
    if port == 465:
        server = smtplib.SMTP_SSL(host, port, context=ctx, timeout=60)
    else:
        server = smtplib.SMTP(host, port, timeout=60)
        server.starttls(context=ctx)
    with server:
        user = (os.environ.get("SMTP_USER") or "").strip()
        if user:
            # Google zeigt App-Passwörter in Vierergruppen an; Leerzeichen entfernen
            passwort = (os.environ.get("SMTP_PASSWORD") or "").replace(" ", "").strip()
            server.login(user, passwort)
        server.send_message(msg, to_addrs=empf)
