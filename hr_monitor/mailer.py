"""Versand der regionalen E-Mail-Berichte per SMTP."""
from __future__ import annotations

import logging
import os
import smtplib
import ssl
from datetime import date, datetime, timedelta
from email.message import EmailMessage
from pathlib import Path

from .config import Config, Region
from .site import env
from .store import Store

log = logging.getLogger(__name__)


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
    """Empfänger aus config.yaml plus GitHub-Secret EMPFAENGER_<REGION>."""
    env_name = "EMPFAENGER_" + region.slug.upper().replace("-", "_")
    extra = [a.strip() for a in os.environ.get(env_name, "").replace(";", ",").split(",") if a.strip()]
    return list(dict.fromkeys(list(region.empfaenger) + extra))


def pending_events(cfg: Config, store: Store, region: Region) -> list[dict]:
    """Noch nicht an diese Region verschickte, aktuelle Einträge."""
    sent_ids = set(store.meta.get("mail_gesendet", {}).get(region.slug, []))
    max_alter = int(cfg.section("email").get("max_alter_tage", 30))
    limit = (date.today() - timedelta(days=max_alter)).isoformat()
    return [e for e in store.events_since(None, region.slug)
            if e["id"] not in sent_ids and (e.get("datum") or e.get("erfasst_am", "")) >= limit]


def send(cfg: Config, store: Store, dry_run: bool = False, outdir: Path | None = None) -> int:
    mcfg = cfg.section("email")
    if not mcfg.get("aktiv", True):
        log.info("E-Mail-Versand deaktiviert")
        return 0
    sent_state = store.meta.setdefault("mail_gesendet", {})
    host = os.environ.get("SMTP_HOST")
    sent = 0
    for reg in cfg.regionen:
        events = pending_events(cfg, store, reg)
        if not events:
            log.info("Region %s: keine neuen Einträge – keine Mail", reg.name)
            continue
        empf = recipients(reg)
        subject, html, text = render(cfg, reg, events)
        if dry_run or not host or not empf:
            if not dry_run:
                log.warning("Region %s: %s – Mail wird nur als Datei abgelegt", reg.name,
                            "SMTP_HOST nicht gesetzt" if not host else "keine Empfänger hinterlegt")
            if outdir:
                outdir.mkdir(parents=True, exist_ok=True)
                (outdir / f"mail-{reg.slug}.html").write_text(html, encoding="utf-8")
                (outdir / f"mail-{reg.slug}.txt").write_text(f"Betreff: {subject}\n\n{text}", encoding="utf-8")
            continue
        msg = EmailMessage()
        msg["Subject"] = subject
        msg["From"] = os.environ.get("MAIL_FROM") or os.environ.get("SMTP_USER", "")
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
            if os.environ.get("SMTP_USER"):
                server.login(os.environ["SMTP_USER"], os.environ.get("SMTP_PASSWORD", ""))
            server.send_message(msg, to_addrs=empf)
        # Erst nach erfolgreichem Versand als verschickt markieren
        sent_state.setdefault(reg.slug, []).extend(e["id"] for e in events)
        log.info("Mail an %d Empfänger (%s) gesendet: %d Einträge", len(empf), reg.name, len(events))
        sent += 1
    return sent
