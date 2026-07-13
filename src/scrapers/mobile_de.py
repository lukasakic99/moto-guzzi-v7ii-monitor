"""
mobile.de scraper.

mobile.de is more defensive than Kleinanzeigen (heavier anti-bot, more dynamic
markup), so this scraper is written to depend on the *stable* parts of the page:

* On search pages we collect every anchor pointing at a vehicle detail page
  (``.../fahrzeuge/details.html?id=NNN``) — that URL shape changes far less
  often than the surrounding card CSS classes.
* On detail pages we read the technical-data ``dt``/``dd`` pairs and, as a
  fallback, any embedded ``application/ld+json`` block.

Everything is best-effort: a blocked or restyled page yields fewer results, not
a crash. The optional ScraperAPI proxy (German exit IP) makes this dramatically
more reliable from GitHub Actions runners.
"""

from __future__ import annotations

import json
import logging
import re
from collections.abc import Iterable
from urllib.parse import parse_qs, urlencode, urljoin, urlparse

from bs4 import BeautifulSoup

import config
from .. import parsing
from ..models import Listing, make_listing_id
from .base import BaseScraper

log = logging.getLogger("scraper.mobile_de")

SEARCH_URL = "https://suchen.mobile.de/fahrzeuge/search.html"
BASE_URL = "https://suchen.mobile.de"

# Moto Guzzi's manufacturer id on mobile.de. If mobile.de ever renumbers makes,
# this is the one value to update (the rest of the search is free-text + filter).
MOTO_GUZZI_MAKE_ID = "17700"

DETAIL_RE = re.compile(r"/fahrzeuge/details\.html\?id=(\d+)", re.I)


class MobileDeScraper(BaseScraper):
    name = "mobile.de"
    label = "mobile.de"

    # ------------------------------------------------------------------ #
    # Search URLs
    # ------------------------------------------------------------------ #
    def _page_url(self, page: int) -> str:
        params = {
            "isSearchRequest": "true",
            "vc": "Motorbike",          # vehicle category: motorbike
            "s": "Motorbike",
            "ms": f"{MOTO_GUZZI_MAKE_ID};;;",  # make = Moto Guzzi, any model
            "q": config.SEARCH_TERM,    # free-text narrowing ("Moto Guzzi V7")
            "sb": "doc",                # sort by listing date ...
            "od": "down",               # ... newest first
            "pageNumber": str(page),
        }
        if config.POSTAL_CODE:
            params["zipcode"] = config.POSTAL_CODE
            params["zipcodeRadius"] = str(config.RADIUS_KM)
        return f"{SEARCH_URL}?{urlencode(params)}"

    def search_pages(self) -> Iterable[str]:
        referer = "https://www.mobile.de/"
        for page in range(1, config.MAX_SEARCH_PAGES + 1):
            url = self._page_url(page)
            log.info("Fetching search page %d: %s", page, url)
            html = self.http.get(url, referer=referer)
            referer = url
            if not html:
                break
            yield html
            self.http.polite_delay()

    # ------------------------------------------------------------------ #
    # Parsing search-result pages
    # ------------------------------------------------------------------ #
    def parse_results(self, html: str) -> list[Listing]:
        soup = BeautifulSoup(html, "lxml")
        seen: dict[str, Listing] = {}

        for anchor in soup.find_all("a", href=True):
            match = DETAIL_RE.search(anchor["href"])
            if not match:
                continue
            native_id = match.group(1)
            if native_id in seen:
                continue
            url = urljoin(BASE_URL, anchor["href"].split("&")[0]
                          if "?" in anchor["href"] else anchor["href"])
            # Preserve the id query param that split("&") may have kept.
            if "id=" not in url:
                url = urljoin(BASE_URL, anchor["href"])

            card = anchor
            # Walk up a couple of levels to reach the card container for text.
            for _ in range(3):
                if card.parent is not None:
                    card = card.parent

            title = self._first_text(anchor, card)
            price_raw = self._find_price(card)
            image_url = self._find_image(card)

            seen[native_id] = Listing(
                id=make_listing_id(self.name, native_id, url),
                source=self.name,
                url=url,
                title=title,
                price_raw=price_raw,
                price_eur=parsing.parse_price(price_raw),
                image_url=image_url,
            )

        listings = list(seen.values())
        log.info("Parsed %d detail links from a search page.", len(listings))
        return listings

    @staticmethod
    def _first_text(anchor, card) -> str:
        text = anchor.get_text(" ", strip=True)
        if text and len(text) > 3:
            return text[:200]
        heading = card.find(["h2", "h3"]) if card else None
        return heading.get_text(" ", strip=True)[:200] if heading else ""

    @staticmethod
    def _find_price(card) -> str:
        if not card:
            return ""
        node = card.find(string=re.compile(r"\d[\d.\s]*\s*€"))
        return node.strip() if node else ""

    @staticmethod
    def _find_image(card) -> str:
        if not card:
            return ""
        img = card.find("img")
        if not img:
            return ""
        for attr in ("src", "data-src", "srcset"):
            val = img.get(attr)
            if val and "http" in val:
                return val.split(",")[0].strip().split(" ")[0]
        return ""

    # ------------------------------------------------------------------ #
    # Detail-page enrichment
    # ------------------------------------------------------------------ #
    def enrich(self, listing: Listing) -> None:
        html = self.http.get(listing.url, referer="https://www.mobile.de/")
        if not html:
            return
        soup = BeautifulSoup(html, "lxml")

        # 1) Technical-data definition lists (dt = label, dd = value).
        data: dict[str, str] = {}
        for dl in soup.find_all("dl"):
            terms = dl.find_all("dt")
            defs = dl.find_all("dd")
            for term, definition in zip(terms, defs):
                key = term.get_text(" ", strip=True).lower()
                data[key] = definition.get_text(" ", strip=True)

        def field(*keys: str) -> str:
            for key in keys:
                for label, value in data.items():
                    if key in label:
                        return value
            return ""

        ez = field("erstzulassung", "registration")
        if ez:
            listing.first_registration = (
                parsing.parse_first_registration(ez) or listing.first_registration)
            listing.year = parsing.parse_year(ez) or listing.year

        km = field("kilometer", "laufleistung", "mileage")
        if km:
            listing.mileage_km = parsing.parse_mileage(km) or listing.mileage_km

        power = field("leistung", "power")
        if power:
            listing.power_ps = parsing.parse_power_ps(power) or listing.power_ps

        # 2) JSON-LD fallback for price / mileage / model year.
        self._apply_json_ld(soup, listing)

        # 3) Title + description feed the classifier's keyword checks.
        title_el = soup.find(["h1"])
        if title_el and not listing.title:
            listing.title = title_el.get_text(" ", strip=True)[:200]

        desc_el = soup.select_one(
            "[data-testid='description'], .description, #ad-description")
        if desc_el:
            text = desc_el.get_text(" ", strip=True)
            listing.description = f"{listing.description} {text}".strip()[:1500]

    @staticmethod
    def _apply_json_ld(soup: BeautifulSoup, listing: Listing) -> None:
        for script in soup.find_all("script", type="application/ld+json"):
            try:
                payload = json.loads(script.string or "{}")
            except (json.JSONDecodeError, TypeError):
                continue
            candidates = payload if isinstance(payload, list) else [payload]
            for obj in candidates:
                if not isinstance(obj, dict):
                    continue
                offers = obj.get("offers") or {}
                price = offers.get("price") if isinstance(offers, dict) else None
                if price and listing.price_eur is None:
                    parsed = parsing.parse_price(str(price))
                    if parsed:
                        listing.price_eur = parsed
                        listing.price_raw = listing.price_raw or f"{parsed} €"
                odo = obj.get("mileageFromOdometer") or {}
                value = odo.get("value") if isinstance(odo, dict) else None
                if value and listing.mileage_km is None:
                    listing.mileage_km = parsing.parse_mileage(f"{value} km")
                model_date = obj.get("modelDate") or obj.get("productionDate")
                if model_date and listing.year is None:
                    listing.year = parsing.parse_year(str(model_date))
