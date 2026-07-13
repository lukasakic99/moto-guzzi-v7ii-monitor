"""
Kleinanzeigen.de scraper.

Kleinanzeigen renders its search results server-side, so BeautifulSoup can read
them directly. The site *does* aggressively challenge datacenter IPs, which is
exactly what the optional ScraperAPI proxy (see ``config``/``http_client``) is
for. If a page is blocked we simply get fewer/zero results that run and the rest
of the pipeline carries on.

NOTE: marketplace HTML changes over time. Selectors are kept in one place and
written defensively (every lookup tolerates a missing element) so that a layout
tweak degrades gracefully instead of throwing.
"""

from __future__ import annotations

import logging
from collections.abc import Iterable
from urllib.parse import urljoin

from bs4 import BeautifulSoup

import config
from .. import parsing
from ..models import Listing, make_listing_id
from .base import BaseScraper

log = logging.getLogger("scraper.kleinanzeigen")

BASE_URL = "https://www.kleinanzeigen.de"
MOTORCYCLE_CATEGORY = "c305"  # "Motorräder & Motorroller"


class KleinanzeigenScraper(BaseScraper):
    name = "kleinanzeigen"
    label = "Kleinanzeigen"

    # ------------------------------------------------------------------ #
    # Search URLs
    # ------------------------------------------------------------------ #
    def _slug(self) -> str:
        return config.SEARCH_TERM.strip().lower().replace(" ", "-")

    def _page_url(self, page: int) -> str:
        """
        Build the search URL for a given 1-based page.

        Example (page 2):
        https://www.kleinanzeigen.de/s-motorraeder/seite:2/moto-guzzi-v7/k0c305
        """
        slug = self._slug()
        seite = "" if page <= 1 else f"seite:{page}/"
        return f"{BASE_URL}/s-motorraeder/{seite}{slug}/k0{MOTORCYCLE_CATEGORY}"

    def search_pages(self) -> Iterable[str]:
        referer = BASE_URL
        for page in range(1, config.MAX_SEARCH_PAGES + 1):
            url = self._page_url(page)
            log.info("Fetching search page %d: %s", page, url)
            html = self.http.get(url, referer=referer)
            referer = url
            if not html:
                # Blocked or empty — stop paging, nothing more to gain.
                break
            yield html
            self.http.polite_delay()

    # ------------------------------------------------------------------ #
    # Parsing search-result cards
    # ------------------------------------------------------------------ #
    def parse_results(self, html: str) -> list[Listing]:
        soup = BeautifulSoup(html, "lxml")
        articles = soup.select("article.aditem")
        listings: list[Listing] = []

        for art in articles:
            href = art.get("data-href") or ""
            adid = art.get("data-adid") or ""
            if not href:
                link = art.select_one("a.ellipsis, .text-module-begin a")
                href = link.get("href") if link else ""
            if not href:
                continue
            url = urljoin(BASE_URL, href)

            title_el = art.select_one(".text-module-begin a, h2 a, .ellipsis")
            title = title_el.get_text(strip=True) if title_el else ""

            price_el = art.select_one(".aditem-main--middle--price-shipping--price, "
                                      ".aditem-main--middle--price")
            price_raw = price_el.get_text(strip=True) if price_el else ""

            loc_el = art.select_one(".aditem-main--top--left")
            location = loc_el.get_text(" ", strip=True) if loc_el else ""

            desc_el = art.select_one(".aditem-main--middle--description")
            description = desc_el.get_text(" ", strip=True) if desc_el else ""

            image_url = self._extract_image(art)

            # Vehicle cards often expose km / year as "simpletag" chips.
            tags = [t.get_text(" ", strip=True)
                    for t in art.select(".simpletag, .aditem-main--bottom .simpletag")]
            tag_text = " ".join(tags)

            listing = Listing(
                id=make_listing_id(self.name, adid, url),
                source=self.name,
                url=url,
                title=title,
                price_raw=price_raw,
                price_eur=parsing.parse_price(price_raw),
                mileage_km=parsing.parse_mileage(tag_text),
                first_registration=parsing.parse_first_registration(tag_text),
                year=parsing.parse_year(tag_text),
                location=location,
                image_url=image_url,
                description=description,
            )
            listings.append(listing)

        log.info("Parsed %d cards from a search page.", len(listings))
        return listings

    @staticmethod
    def _extract_image(art) -> str:
        img = art.select_one(".aditem-image img, .imagebox img, img")
        if not img:
            return ""
        for attr in ("src", "data-imgsrc", "data-src"):
            val = img.get(attr)
            if val and val.startswith("http"):
                return val
        srcset = img.get("srcset") or ""
        if srcset:
            first = srcset.split(",")[0].strip().split(" ")[0]
            if first.startswith("http"):
                return first
        return ""

    # ------------------------------------------------------------------ #
    # Detail-page enrichment
    # ------------------------------------------------------------------ #
    def enrich(self, listing: Listing) -> None:
        html = self.http.get(listing.url, referer=self._page_url(1))
        if not html:
            return
        soup = BeautifulSoup(html, "lxml")

        # Structured attribute list: label -> value.
        attrs: dict[str, str] = {}
        for row in soup.select(".addetailslist--detail"):
            value_el = row.select_one(".addetailslist--detail--value")
            if not value_el:
                continue
            label = row.get_text(" ", strip=True).replace(
                value_el.get_text(" ", strip=True), "").strip().lower()
            attrs[label] = value_el.get_text(" ", strip=True)

        def attr(*keys: str) -> str:
            for key in keys:
                for label, value in attrs.items():
                    if key in label:
                        return value
            return ""

        km = attr("kilometerstand")
        if km:
            listing.mileage_km = parsing.parse_mileage(km) or listing.mileage_km

        ez = attr("erstzulassung")
        if ez:
            listing.first_registration = (
                parsing.parse_first_registration(ez) or listing.first_registration)
            listing.year = parsing.parse_year(ez) or listing.year

        power = attr("leistung", "ps", "kw")
        if power:
            listing.power_ps = parsing.parse_power_ps(power) or listing.power_ps

        # Full description text drives the classifier's keyword checks.
        desc_el = soup.select_one("#viewad-description-text, .viewad-description")
        if desc_el:
            text = desc_el.get_text(" ", strip=True)
            listing.description = f"{listing.description} {text}".strip()[:1500]

        # Detail page usually has the authoritative price.
        price_el = soup.select_one("#viewad-price, .boxedarticle--price")
        if price_el:
            price_raw = price_el.get_text(" ", strip=True)
            listing.price_raw = price_raw or listing.price_raw
            listing.price_eur = parsing.parse_price(price_raw) or listing.price_eur
