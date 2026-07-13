"""
Common scraper scaffolding.

Each concrete scraper implements two things:

* :meth:`search_pages` — yield the search-result HTML pages to parse.
* :meth:`parse_results` — turn one search page into a list of *basic* Listings
  (title, price, url, image, location — whatever the result card exposes).
* :meth:`enrich`      — optionally fetch a listing's detail page to fill in
  year / power / description, which the classifier relies on.

:meth:`run` ties it together, applying the polite-delay and detail-fetch caps
defined in ``config``.
"""

from __future__ import annotations

import logging
from abc import ABC, abstractmethod
from collections.abc import Iterable

import config
from ..classifier import is_probably_other_model
from ..http_client import HttpClient
from ..models import Listing

log = logging.getLogger("scraper")


class BaseScraper(ABC):
    #: Short identifier stored on every listing (e.g. "kleinanzeigen").
    name: str = "base"
    #: Human-readable label for the dashboard.
    label: str = "Base"

    def __init__(self) -> None:
        self.http = HttpClient()

    # ------------------------------------------------------------------ #
    # Methods each concrete scraper must implement
    # ------------------------------------------------------------------ #
    @abstractmethod
    def search_pages(self) -> Iterable[str]:
        """Yield the raw HTML of each search-result page to parse."""

    @abstractmethod
    def parse_results(self, html: str) -> list[Listing]:
        """Parse one search-result page into a list of basic listings."""

    @abstractmethod
    def enrich(self, listing: Listing) -> None:
        """Fetch and parse ``listing``'s detail page in place (best effort)."""

    # ------------------------------------------------------------------ #
    # Orchestration shared by every scraper
    # ------------------------------------------------------------------ #
    def run(self, known_ids: set[str]) -> list[Listing]:
        """
        Scrape this marketplace and return the collected listings.

        ``known_ids`` lets us skip the (expensive, rate-limited) detail fetch for
        adverts we already have — we still return them so ``last_seen`` refreshes.
        Never raises: any failure is logged and yields a partial/empty result.
        """
        collected: dict[str, Listing] = {}
        detail_fetches = 0

        try:
            for page_html in self.search_pages():
                if not page_html:
                    continue
                for listing in self.parse_results(page_html):
                    if listing.id in collected:
                        continue
                    collected[listing.id] = listing
        except Exception as exc:  # noqa: BLE001 — never let one site crash the run
            log.exception("%s: search phase failed: %s", self.name, exc)

        # Enrich only new, plausibly-relevant listings, up to the per-site cap.
        skipped_obvious = 0
        if config.FETCH_DETAIL_PAGES:
            for listing in collected.values():
                if listing.id in known_ids:
                    continue
                # Save the fetch budget: don't fetch a detail page for a listing
                # whose title already proves it is a different model.
                if is_probably_other_model(listing.title):
                    skipped_obvious += 1
                    continue
                if detail_fetches >= config.MAX_DETAIL_FETCHES_PER_SITE:
                    log.info("%s: hit detail-fetch cap (%d).",
                             self.name, config.MAX_DETAIL_FETCHES_PER_SITE)
                    break
                try:
                    self.http.polite_delay()
                    self.enrich(listing)
                except Exception as exc:  # noqa: BLE001
                    log.warning("%s: enrich failed for %s: %s",
                                self.name, listing.url, exc)
                detail_fetches += 1

        log.info("%s: collected %d listings (%d detail pages fetched, "
                 "%d skipped as obvious non-matches).",
                 self.name, len(collected), detail_fetches, skipped_obvious)
        return list(collected.values())
