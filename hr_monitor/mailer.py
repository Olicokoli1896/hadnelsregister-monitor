"""Versand der regionalen E-Mail-Berichte per SMTP."""
from __future__ import annotations

import logging
import os
import smtplib
import ssl
from datetime import datetime
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


def send(cfg: Config, store: Store, dry_run: bool = False, outdir: Path | None = None) -> int:
    mcfg = cfg.section("email")
    if not mcfg.get("aktiv", True):
        log.info("E-Mail-Versand deaktiviert")
        return 0
    sent_state = store.meta.setdefault("mail_versand", {})
    host = os.environ.get("SMTP_HOST")
    sent = 0
    for reg in cfg.regionen:
        since = sent_state.get(reg.slug)
        events = store.events_since(since, reg.slug)
        if not events and mcfg.get("nur_bei_neuen_eintraegen", True):
            log.info("Region %s: keine neuen Einträge – keine Mail", reg.name)
            continue
        if not reg.empfaenger:
            continue
        subject, html, text = render(cfg, reg, events)
        if dry_run or not host:
            if not host and not dry_run:
                log.warning("SMTP_HOST nicht gesetzt – Mail für %s wird nur als Datei abgelegt", reg.name)
            if outdir:
                outdir.mkdir(parents=True, exist_ok=True)
                (outdir / f"mail-{reg.slug}.html").write_text(html, encoding="utf-8")
                (outdir / f"mail-{reg.slug}.txt").write_text(f"Betreff: {subject}\n\n{text}", encoding="utf-8")
            continue
        msg = EmailMessage()
        msg["Subject"] = subject
        msg["From"] = os.environ.get("MAIL_FROM") or os.environ.get("SMTP_USER", "")
        msg["To"] = msg["From"]
        # Empfänger im BCC, damit sie sich gegenseitig nicht sehen
        msg.set_content(text)
        msg.add_alternative(html, subtype="html")
        port = int(os.environ.get("SMTP_PORT", "587"))
        ctx = ssl.create_default_context()
        if port == 465:
            server = smtplib.SMTP_SSL(host, port, context=ctx, timeout=60)
        else:
            server = smtplib.SMTP(host, port, timeout=60)
            server.starttls(context=ctx)
        with server:
            if os.environ.get("SMTP_USER"):
                server.login(os.environ["SMTP_USER"], os.environ.get("SMTP_PASSWORD", ""))
            server.send_message(msg, to_addrs=list(reg.empfaenger))
        sent_state[reg.slug] = datetime.now().isoformat(timespec="seconds")
        log.info("Mail an %d Empfänger (%s) gesendet: %d Einträge", len(reg.empfaenger), reg.name, len(events))
        sent += 1
    return sent
