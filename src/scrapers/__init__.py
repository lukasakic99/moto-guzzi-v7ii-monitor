"""Marketplace scraper implementations."""

from __future__ import annotations

import config

from .base import BaseScraper
from .kleinanzeigen import KleinanzeigenScraper
from .mobile_de import MobileDeScraper


def enabled_scrapers() -> list[BaseScraper]:
    """Return an instance of every scraper enabled in ``config``."""
    scrapers: list[BaseScraper] = []
    if config.ENABLE_KLEINANZEIGEN:
        scrapers.append(KleinanzeigenScraper())
    if config.ENABLE_MOBILE_DE:
        scrapers.append(MobileDeScraper())
    return scrapers


__all__ = [
    "BaseScraper",
    "KleinanzeigenScraper",
    "MobileDeScraper",
    "enabled_scrapers",
]
