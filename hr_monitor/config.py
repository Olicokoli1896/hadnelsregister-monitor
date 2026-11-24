"""Laden und Aufbereiten der Konfiguration."""
from __future__ import annotations

import os
import re
import unicodedata
from dataclasses import dataclass, field
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parent.parent


def slugify(text: str) -> str:
    text = text.replace("ß", "ss").replace("ä", "ae").replace("ö", "oe").replace("ü", "ue")
    text = text.replace("Ä", "ae").replace("Ö", "oe").replace("Ü", "ue")
    text = unicodedata.normalize("NFKD", text).encode("ascii", "ignore").decode()
    return re.sub(r"[^a-z0-9]+", "-", text.lower()).strip("-") or "region"


@dataclass
class Region:
    name: str
    mittelpunkt: str
    radius_km: float
    empfaenger: list[str] = field(default_factory=list)
    registergerichte: list[str] = field(default_factory=list)
    lat: float = 0.0
    lon: float = 0.0

    @property
    def slug(self) -> str:
        return slugify(self.name)


@dataclass
class Config:
    raw: dict
    regionen: list[Region]

    def __getitem__(self, key):
        return self.raw[key]

    def get(self, key, default=None):
        return self.raw.get(key, default)

    def section(self, key) -> dict:
        return self.raw.get(key) or {}


def load_config(path: str | Path | None = None) -> Config:
    path = Path(path) if path else ROOT / "config.yaml"
    raw = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    # Adresse der Website (z. B. Cloudflare Pages) lässt sich ohne Codeänderung über
    # die GitHub-Variable SITE_URL setzen; sie hat Vorrang vor config.yaml.
    site_url = (os.environ.get("SITE_URL") or "").strip()
    if site_url:
        raw["site_url"] = site_url
    regionen = []
    for r in raw.get("regionen") or []:
        regionen.append(
            Region(
                name=str(r["name"]),
                mittelpunkt=str(r["mittelpunkt"]),
                radius_km=float(r.get("radius_km", 30)),
                empfaenger=list(r.get("empfaenger") or []),
                registergerichte=list(r.get("registergerichte") or []),
            )
        )
    if not regionen:
        raise ValueError("config.yaml: mindestens eine Region unter 'regionen' angeben")
    return Config(raw=raw, regionen=regionen)
