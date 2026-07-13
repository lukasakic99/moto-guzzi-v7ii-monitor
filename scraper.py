#!/usr/bin/env python3
"""
Moto Guzzi V7 II marketplace monitor — main entry point / orchestrator.

Pipeline
--------
1. Load the existing ``listings.json`` database.
2. Scrape every enabled marketplace (Kleinanzeigen, mobile.de). New adverts get
   their detail page fetched so the classifier has year / power / description.
3. Classify each *new* candidate as a genuine Moto Guzzi V7 II and drop anything
   that is a different model or fails the optional price/year filters.
4. Merge the survivors into the database (append new, refresh known, keep the
   list sorted newest-first) and write it back.
5. Regenerate the static ``index.html`` dashboard from the full database.

The whole thing is designed to *never* crash on network/anti-bot failures: a
blocked site simply contributes nothing that run and the dashboard is always
rebuilt from whatever is already stored.

Usage
-----
    python scraper.py                # full run: scrape + rebuild dashboard
    python scraper.py --no-scrape    # only rebuild index.html from listings.json
    python scraper.py --verbose      # debug-level logging
"""

from __future__ import annotations

import argparse
import logging
import sys

import config
from src import dashboard, storage
from src.classifier import classify
from src.models import Listing
from src.scrapers import enabled_scrapers


def _configure_logging(verbose: bool) -> None:
    logging.basicConfig(
        level=logging.DEBUG if verbose else logging.INFO,
        format="%(asctime)s  %(levelname)-7s %(name)s: %(message)s",
        datefmt="%H:%M:%S",
        stream=sys.stdout,
    )


def _passes_filters(listing: Listing) -> bool:
    """Apply the optional price/year filters from ``config`` to a candidate."""
    price = listing.price_eur
    if config.MIN_PRICE_EUR is not None and price is not None and price < config.MIN_PRICE_EUR:
        return False
    if config.MAX_PRICE_EUR is not None and price is not None and price > config.MAX_PRICE_EUR:
        return False
    year = listing.year
    if config.MIN_YEAR is not None and year is not None and year < config.MIN_YEAR:
        return False
    if config.MAX_YEAR is not None and year is not None and year > config.MAX_YEAR:
        return False
    return True


def scrape_all(known_ids: set[str]) -> list[Listing]:
    """Run every enabled scraper and return the combined raw listings."""
    collected: list[Listing] = []
    for scraper in enabled_scrapers():
        log = logging.getLogger("run")
        log.info("── Scraping %s ──", scraper.label)
        try:
            collected.extend(scraper.run(known_ids))
        except Exception as exc:  # noqa: BLE001 — isolate per-site failures
            log.exception("%s failed entirely: %s", scraper.label, exc)
    return collected


def run(no_scrape: bool = False) -> int:
    """Execute the full pipeline. Returns the number of newly found listings."""
    log = logging.getLogger("run")
    existing = storage.load_listings(config.LISTINGS_FILE)
    existing_ids = {l.id for l in existing}

    keep: list[Listing] = []
    if no_scrape:
        log.info("--no-scrape set: rebuilding dashboard from existing data only.")
    else:
        scraped = scrape_all(existing_ids)
        log.info("Scraped %d raw listings across all sites.", len(scraped))

        classified_new = 0
        for listing in scraped:
            if listing.id in existing_ids:
                # Known advert — pass through so last_seen/price refresh, but do
                # not re-classify on the lightweight card data.
                keep.append(listing)
                continue
            listing.classification = classify(listing)
            if not listing.classification.is_v7ii:
                log.debug("Rejected (%s, %.2f): %s",
                          listing.classification.category,
                          listing.classification.confidence, listing.title)
                continue
            if not _passes_filters(listing):
                log.debug("Filtered out by price/year: %s", listing.title)
                continue
            keep.append(listing)
            classified_new += 1
        log.info("%d new candidates passed classification + filters.", classified_new)

    merged, newly_found = storage.merge_listings(existing, keep)
    storage.save_listings(config.LISTINGS_FILE, merged)
    dashboard.generate_html(merged, config.OUTPUT_HTML)

    # ------------------------------------------------------------------ #
    # Human-friendly summary
    # ------------------------------------------------------------------ #
    log.info("=" * 60)
    log.info("Run complete.")
    log.info("  Total listings in database : %d", len(merged))
    log.info("  New this run               : %d", len(newly_found))
    for listing in newly_found:
        log.info("    + [%s] %s — %s (%s)",
                 listing.classification.category,
                 listing.title[:60] or "Ohne Titel",
                 dashboard._fmt_price(listing),
                 listing.source)
    log.info("  Dashboard written to       : %s", config.OUTPUT_HTML.name)
    log.info("=" * 60)
    return len(newly_found)


def main() -> None:
    parser = argparse.ArgumentParser(description="Moto Guzzi V7 II marketplace monitor")
    parser.add_argument("--no-scrape", action="store_true",
                        help="Skip scraping; only rebuild index.html from listings.json")
    parser.add_argument("--verbose", action="store_true",
                        help="Enable debug logging")
    args = parser.parse_args()

    _configure_logging(args.verbose)
    logging.getLogger("run").info(
        "Proxy mode: %s | Sites: %s",
        config.proxy_mode(),
        ", ".join(s.label for s in enabled_scrapers()) or "none",
    )
    run(no_scrape=args.no_scrape)


if __name__ == "__main__":
    main()
