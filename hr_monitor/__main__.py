"""Kommandozeile:

    python -m hr_monitor run            # alle Quellen abrufen, Website bauen, Mails senden
    python -m hr_monitor run --no-mail  # ohne Mailversand
    python -m hr_monitor run --quellen bekanntmachungen,insolvenz
    python -m hr_monitor site           # nur Website neu bauen
    python -m hr_monitor mail --dry-run # Mails nur als Dateien in out/ ablegen
    python -m hr_monitor orte           # Orte im Umkreis der Regionen anzeigen
"""
from __future__ import annotations

import argparse
import logging
import sys

from . import mailer, site
from .classify import Classifier
from .config import ROOT, load_config
from .geo import get_geo, resolve_center
from .net import BudgetExceeded, Throttle
from .sources import Context
from .store import Store

log = logging.getLogger("hr_monitor")


def make_context(config_path=None) -> Context:
    cfg = load_config(config_path)
    geo = get_geo()
    for reg in cfg.regionen:
        reg.lat, reg.lon, _ = resolve_center(geo, reg.mittelpunkt)
    return Context(config=cfg, store=Store(), geo=geo,
                   classifier=Classifier(cfg.get("branchen")))


def cmd_run(args, ctx: Context):
    cfg = ctx.config
    quellen = cfg.section("quellen")
    if args.quellen:
        wanted = set(args.quellen.split(","))
        quellen = {k: (k in wanted) for k in ("bekanntmachungen", "unternehmenssuche", "insolvenz")}
    hr = cfg.section("handelsregister")
    throttle = Throttle(hr.get("sekunden_zwischen_abrufen", 62), hr.get("max_abrufe_pro_lauf", 55))
    if args.schnell:
        throttle.min_interval = 3
    if args.max_abrufe is not None:
        throttle.max_requests = args.max_abrufe
    summary = {}
    if quellen.get("bekanntmachungen"):
        from .sources.bekanntmachungen import Bekanntmachungen
        try:
            summary["Registerbekanntmachungen"] = Bekanntmachungen(ctx, throttle).run()
        except BudgetExceeded:
            log.warning("Abruflimit bei den Registerbekanntmachungen erreicht")
        except Exception:
            log.exception("Registerbekanntmachungen fehlgeschlagen")
        ctx.store.save()
    if quellen.get("unternehmenssuche"):
        from .sources.unternehmenssuche import Unternehmenssuche
        try:
            summary["Unternehmenssuche"] = Unternehmenssuche(ctx, throttle).run()
        except Exception:
            log.exception("Unternehmenssuche fehlgeschlagen")
        ctx.store.save()
    if quellen.get("insolvenz"):
        from .sources.insolvenz import Insolvenz
        try:
            summary["Insolvenzen"] = Insolvenz(ctx).run()
        except Exception:
            log.exception("Insolvenzsuche fehlgeschlagen")
    ctx.store.prune(int(cfg.section("insolvenz").get("aufbewahrung_tage", 180)))
    ctx.store.save()
    log.info("Neue Ereignisse: %s (Abrufe handelsregister.de: %d)", summary, throttle.count)
    site.build(cfg, ctx.store)
    if not args.no_mail:
        mailer.send(cfg, ctx.store, outdir=ROOT / "out")
        ctx.store.save()


def main(argv=None):
    p = argparse.ArgumentParser(prog="hr_monitor")
    p.add_argument("--config", help="Pfad zur config.yaml")
    p.add_argument("-v", "--verbose", action="store_true")
    sub = p.add_subparsers(dest="cmd", required=True)
    r = sub.add_parser("run")
    r.add_argument("--no-mail", action="store_true")
    r.add_argument("--quellen", help="kommagetrennt: bekanntmachungen,unternehmenssuche,insolvenz")
    r.add_argument("--schnell", action="store_true",
                   help="nur zum Testen: kürzere Pausen (Nutzungsbedingungen beachten!)")
    r.add_argument("--max-abrufe", type=int, help="Abruflimit handelsregister.de für diesen Lauf")
    sub.add_parser("site")
    m = sub.add_parser("mail")
    m.add_argument("--dry-run", action="store_true")
    sub.add_parser("orte")
    args = p.parse_args(argv)
    logging.basicConfig(level=logging.DEBUG if args.verbose else logging.INFO,
                        format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    ctx = make_context(args.config)
    if args.cmd == "run":
        cmd_run(args, ctx)
    elif args.cmd == "site":
        site.build(ctx.config, ctx.store)
    elif args.cmd == "mail":
        mailer.send(ctx.config, ctx.store, dry_run=args.dry_run, outdir=ROOT / "out")
        if not args.dry_run:
            ctx.store.save()
    elif args.cmd == "orte":
        for reg in ctx.config.regionen:
            orte = ctx.geo.places_within(reg.lat, reg.lon, reg.radius_km)
            print(f"{reg.name} ({reg.radius_km} km): {len(orte)} Orte")
            print(", ".join(o for o, _, _ in orte))
    return 0


if __name__ == "__main__":
    sys.exit(main())
