"""Erzeugt die statische Website (docs/) aus den gespeicherten Ereignissen."""
from __future__ import annotations

import json
from datetime import date, datetime, timedelta
from pathlib import Path

from jinja2 import Environment, FileSystemLoader, select_autoescape

from .config import ROOT, Config
from .store import EVENT_TYPES, Store

OUT = ROOT / "docs"

GROUPS = {
    "Gründung": ["neugruendung", "neueintragung"],
    "Veränderung": ["umfirmierung", "sitzverlegung", "statusaenderung", "umwandlung",
                    "neue_dokumente", "sonstige_bekanntmachung"],
    "Löschung": ["loeschungsankuendigung"],
    "Insolvenz": ["insolvenz_eroeffnung", "insolvenz_sicherung", "insolvenz_abweisung",
                  "insolvenz_entscheidung", "insolvenz_sonstige"],
}
GROUP_OF = {t: g for g, ts in GROUPS.items() for t in ts}


def env() -> Environment:
    e = Environment(loader=FileSystemLoader(ROOT / "templates"),
                    autoescape=select_autoescape(["html", "j2"]))
    e.filters["de_date"] = lambda s: (datetime.fromisoformat(s[:10]).strftime("%d.%m.%Y")
                                      if s and len(s) >= 10 and s[4] == "-" else (s or ""))
    e.globals.update(EVENT_TYPES=EVENT_TYPES, GROUP_OF=GROUP_OF, GROUPS=GROUPS)
    return e


def visible_events(store: Store, cfg: Config, region_slug: str | None = None) -> list[dict]:
    limit = (date.today() - timedelta(days=int(cfg.get("anzeige_tage", 120)))).isoformat()
    evs = [e for e in store.events.values()
           if (e.get("datum") or e.get("erfasst_am", "")) >= limit
           and (region_slug is None or region_slug in e.get("regionen", []))]
    return sorted(evs, key=lambda e: (e.get("datum") or "", e.get("erfasst_am", "")), reverse=True)


def build(cfg: Config, store: Store, out: Path = OUT) -> list[Path]:
    out.mkdir(parents=True, exist_ok=True)
    e = env()
    now = datetime.now().strftime("%d.%m.%Y %H:%M")
    written = []
    regions = []
    for reg in cfg.regionen:
        evs = visible_events(store, cfg, reg.slug)
        stats = {g: sum(1 for x in evs if GROUP_OF.get(x["typ"]) == g) for g in GROUPS}
        regions.append({"region": reg, "events": evs, "stats": stats})
        html = e.get_template("region.html.j2").render(
            cfg=cfg, region=reg, events=evs, stats=stats, stand=now,
            new_ids=set(store.new_ids))
        p = out / f"{reg.slug}.html"
        p.write_text(html, encoding="utf-8")
        written.append(p)
    html = e.get_template("index.html.j2").render(cfg=cfg, regions=regions, stand=now)
    (out / "index.html").write_text(html, encoding="utf-8")
    written.append(out / "index.html")
    (out / "ereignisse.json").write_text(
        json.dumps(visible_events(store, cfg), ensure_ascii=False, indent=1), encoding="utf-8")
    (out / ".nojekyll").write_text("", encoding="utf-8")
    return written
