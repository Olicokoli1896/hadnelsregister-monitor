"""HTTP-Sitzungen mit Drosselung und Wiederholungen."""
from __future__ import annotations

import logging
import time

import requests

log = logging.getLogger(__name__)

USER_AGENT = "Mozilla/5.0 (compatible; HR-Monitor/0.1; +https://github.com/olicokoli/Recherche-Handelsregister)"


class BudgetExceeded(RuntimeError):
    """Das konfigurierte Abruflimit für diesen Lauf ist erreicht."""


class Throttle:
    """Gemeinsamer Takt + Budget für alle Abrufe auf einem Host."""

    def __init__(self, min_interval: float, max_requests: int | None = None):
        self.min_interval = float(min_interval)
        self.max_requests = max_requests
        self.count = 0
        self._last = 0.0

    def remaining(self) -> int | None:
        if self.max_requests is None:
            return None
        return self.max_requests - self.count

    def wait(self):
        if self.max_requests is not None and self.count >= self.max_requests:
            raise BudgetExceeded(f"Abruflimit von {self.max_requests} erreicht")
        delta = time.monotonic() - self._last
        if self._last and delta < self.min_interval:
            time.sleep(self.min_interval - delta)
        self._last = time.monotonic()
        self.count += 1


class Session:
    """requests.Session mit 'Connection: close', Drosselung und Retries."""

    def __init__(self, throttle: Throttle, timeout: int = 90):
        self.throttle = throttle
        self.timeout = timeout
        self.s = requests.Session()
        self.s.headers.update({"User-Agent": USER_AGENT, "Connection": "close",
                               "Accept-Language": "de-DE,de;q=0.9"})

    def request(self, method: str, url: str, **kw) -> requests.Response:
        kw.setdefault("timeout", self.timeout)
        last_exc = None
        for attempt in range(3):
            self.throttle.wait()
            try:
                r = self.s.request(method, url, **kw)
                if r.status_code >= 500 and attempt < 2:
                    log.warning("%s %s -> HTTP %s, neuer Versuch", method, url, r.status_code)
                    time.sleep(5 * (attempt + 1))
                    continue
                return r
            except requests.RequestException as exc:  # Netzwerkfehler
                last_exc = exc
                log.warning("%s %s fehlgeschlagen (%s), neuer Versuch", method, url, exc)
                time.sleep(5 * (attempt + 1))
        raise last_exc or RuntimeError(f"{method} {url} fehlgeschlagen")

    def get(self, url, **kw):
        return self.request("GET", url, **kw)

    def post(self, url, **kw):
        return self.request("POST", url, **kw)
