"""Robust fetching helpers shared by League providers: caching, retries, rate limit.

We prefer official public pages via plain HTTP. No authentication or captcha is
bypassed; a provider that returns 403/blocked is reported as unavailable.
"""
from __future__ import annotations

import hashlib
import logging
import threading
import time
from pathlib import Path
from urllib.parse import urlparse

import httpx

from ..config import settings

logger = logging.getLogger(__name__)


_lock = threading.Lock()
_last_request: dict[str, float] = {}
_client_lock = threading.Lock()
_http_client: httpx.Client | None = None


def _client() -> httpx.Client:
    """Shared pooled client: one TLS handshake per host instead of one per call.

    The previous code built a fresh httpx.Client for every request, so every
    provider call paid a full TLS handshake again — the bulk of the slow
    "Loading competitions" wait on slower links.
    """
    global _http_client
    with _client_lock:
        if _http_client is None:
            _http_client = httpx.Client(timeout=20, follow_redirects=True,
                                        limits=httpx.Limits(max_keepalive_connections=8, max_connections=16))
        return _http_client


class ProviderUnavailable(Exception):
    pass


class FetchClient:
    """Thin wrapper providing caching, backoff retries, timeouts and rate limit."""

    def __init__(self, provider: str = "generic", min_interval: float = 1.0,
                 cache_seconds: float = 3600.0, force: bool = False):
        self.provider = provider
        self.min_interval = min_interval
        self.cache_seconds = cache_seconds
        self.force = force
        self._headers = {
            "User-Agent": "Mozilla/5.0 (X11; Linux x86_64) ModuloAFarfallaLeagueSync/1.0 "
                          "(football video analysis league import)",
            "Accept": "text/html,application/xhtml+xml",
        }

    def _cache_dir(self) -> Path:
        return settings.storage_root / "league-cache" / self.provider

    def _cache_path(self, url: str) -> Path:
        key = hashlib.sha1(url.encode()).hexdigest()[:20]
        return self._cache_dir() / f"{key}.html"

    def _rate_wait(self, url: str) -> None:
        host = urlparse(url).netloc
        with _lock:
            now = time.monotonic()
            last = _last_request.get(host, 0.0)
            wait = max(0.0, self.min_interval - (now - last))
            _last_request[host] = now + wait
        if wait:
            time.sleep(wait)

    def get(self, url: str, *, use_cache: bool = True) -> str:
        cache_path = self._cache_path(url)
        if use_cache and not self.force and cache_path.exists():
            age = time.time() - cache_path.stat().st_mtime
            if age < self.cache_seconds:
                return cache_path.read_text(encoding="utf-8", errors="ignore")

        last_err: Exception | None = None
        for attempt in range(3):
            self._rate_wait(url)
            try:
                resp = _client().get(url, headers=self._headers)
                if resp.status_code in (403, 401, 429):
                    raise ProviderUnavailable(f"{self.provider} blocked automated access ({resp.status_code})")
                resp.raise_for_status()
                cache_path.parent.mkdir(parents=True, exist_ok=True)
                cache_path.write_text(resp.text, encoding="utf-8")
                return resp.text
            except ProviderUnavailable:
                raise
            except Exception as exc:  # network/5xx -> backoff
                last_err = exc
                logger.warning("provider fetch failed attempt %s for %s: %s", attempt + 1, url, exc)
                time.sleep(2 ** attempt)
        raise ProviderUnavailable(f"{self.provider} unavailable: {last_err}")

    def get_binary(self, url: str, max_bytes: int = 5_000_000) -> bytes | None:
        """Fetch a small binary asset (e.g. team crest). Not cached on disk:
        callers only invoke it when the asset is missing locally, and the
        per-host rate limit still applies."""
        last_err: Exception | None = None
        for attempt in range(3):
            self._rate_wait(url)
            try:
                resp = _client().get(url, headers=self._headers)
                if resp.status_code in (403, 401, 429):
                    raise ProviderUnavailable(f"{self.provider} blocked automated access ({resp.status_code})")
                if resp.status_code == 404:  # genuinely missing asset: no retries
                    return None
                resp.raise_for_status()
                if len(resp.content) > max_bytes or not resp.content:
                    logger.warning("provider asset rejected by size/empty: %s", url)
                    return None
                return resp.content
            except ProviderUnavailable:
                raise
            except Exception as exc:  # network/5xx -> backoff
                last_err = exc
                logger.warning("provider binary fetch failed attempt %s for %s: %s", attempt + 1, url, exc)
                time.sleep(2 ** attempt)
        raise ProviderUnavailable(f"{self.provider} unavailable: {last_err}")
