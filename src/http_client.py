"""
Resilient HTTP client used by every scraper.

Features
--------
* Browser-like headers with a per-run User-Agent chosen from a small pool.
* Optional proxying via ScraperAPI (``SCRAPER_API_KEY``) or a generic HTTP proxy
  (``PROXY_URL``). When neither is configured it falls back to direct requests.
* Automatic retries with exponential backoff and polite, jittered delays.
* Never raises on network errors: ``get()`` returns ``None`` so a single blocked
  site can never crash the whole run (graceful degradation).
"""

from __future__ import annotations

import logging
import random
import time
from urllib.parse import urlencode

import requests

import config

log = logging.getLogger("http")


class HttpClient:
    """A thin, defensive wrapper around a ``requests.Session``."""

    def __init__(self) -> None:
        self.session = requests.Session()
        self.user_agent = random.choice(config.USER_AGENTS)
        self.mode = config.proxy_mode()
        log.info("HTTP client initialised (proxy mode: %s)", self.mode)

    # ------------------------------------------------------------------ #
    # Header construction
    # ------------------------------------------------------------------ #
    def _headers(self, referer: str | None = None) -> dict[str, str]:
        headers = {
            "User-Agent": self.user_agent,
            "Accept": (
                "text/html,application/xhtml+xml,application/xml;q=0.9,"
                "image/avif,image/webp,*/*;q=0.8"
            ),
            "Accept-Language": "de-DE,de;q=0.9,en;q=0.8",
            "Accept-Encoding": "gzip, deflate, br",
            "Connection": "keep-alive",
            "Upgrade-Insecure-Requests": "1",
            "Sec-Fetch-Dest": "document",
            "Sec-Fetch-Mode": "navigate",
            "Sec-Fetch-Site": "none",
            "Sec-Fetch-User": "?1",
        }
        if referer:
            headers["Referer"] = referer
        return headers

    # ------------------------------------------------------------------ #
    # Request routing (direct / ScraperAPI / generic proxy)
    # ------------------------------------------------------------------ #
    def _prepare(
        self, url: str, scraper_params: dict | None = None
    ) -> tuple[str, dict | None]:
        """Return the (possibly rewritten) request URL and requests-proxies.

        ``scraper_params`` are extra ScraperAPI options (e.g. ``render``,
        ``ultra_premium``) applied only to this request — used by mobile.de.
        """
        if self.mode == "scraperapi":
            params = {
                "api_key": config.SCRAPER_API_KEY,
                "url": url,
                "country_code": config.SCRAPER_API_COUNTRY,
                # keep_headers lets ScraperAPI forward our language/UA hints
                "keep_headers": "true",
            }
            if scraper_params:
                params.update(scraper_params)
            return f"{config.SCRAPER_API_ENDPOINT}?{urlencode(params)}", None
        if self.mode == "proxy":
            return url, {"http": config.PROXY_URL, "https": config.PROXY_URL}
        return url, None

    # ------------------------------------------------------------------ #
    # Public API
    # ------------------------------------------------------------------ #
    def get(
        self,
        url: str,
        referer: str | None = None,
        scraper_params: dict | None = None,
    ) -> str | None:
        """
        Fetch ``url`` and return the response body as text, or ``None`` on
        failure after all retries are exhausted.

        ``scraper_params`` passes per-request ScraperAPI options (see
        :meth:`_prepare`).
        """
        request_url, proxies = self._prepare(url, scraper_params)

        for attempt in range(1, config.MAX_RETRIES + 1):
            try:
                resp = self.session.get(
                    request_url,
                    headers=self._headers(referer),
                    proxies=proxies,
                    timeout=config.REQUEST_TIMEOUT,
                    allow_redirects=True,
                )
            except requests.RequestException as exc:
                log.warning("Attempt %d/%d failed for %s: %s",
                            attempt, config.MAX_RETRIES, url, exc)
            else:
                if resp.status_code == 200 and resp.text:
                    return resp.text
                # 403/429/503 are the classic anti-bot / rate-limit responses.
                log.warning("Attempt %d/%d for %s returned HTTP %s",
                            attempt, config.MAX_RETRIES, url, resp.status_code)

            if attempt < config.MAX_RETRIES:
                backoff = config.RETRY_BACKOFF_SECONDS * (2 ** (attempt - 1))
                time.sleep(backoff + random.uniform(0, config.REQUEST_JITTER_SECONDS))

        log.error("Giving up on %s after %d attempts", url, config.MAX_RETRIES)
        return None

    @staticmethod
    def polite_delay() -> None:
        """Sleep a base + jittered amount between successive requests."""
        time.sleep(config.REQUEST_DELAY_SECONDS +
                   random.uniform(0, config.REQUEST_JITTER_SECONDS))
