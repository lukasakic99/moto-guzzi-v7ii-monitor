"""
Central configuration for the Moto Guzzi V7 II marketplace monitor.

Everything that you might reasonably want to tweak lives here so you never have
to dig through the scraping/classification logic. All values have sensible
defaults; the optional proxy is driven entirely by environment variables so no
secrets are ever committed to the repository.
"""

from __future__ import annotations

import os
from pathlib import Path

# --------------------------------------------------------------------------- #
# Paths
# --------------------------------------------------------------------------- #
BASE_DIR = Path(__file__).resolve().parent
LISTINGS_FILE = BASE_DIR / "listings.json"          # our JSON "database"
OUTPUT_HTML = BASE_DIR / "index.html"               # the generated dashboard

# --------------------------------------------------------------------------- #
# What we are hunting for
# --------------------------------------------------------------------------- #
# We deliberately search BROADLY ("Moto Guzzi V7") rather than only "V7 II".
# Many genuine V7 II bikes are listed as just "V7", "V7 750" or with the wrong
# generation. The classifier (src/classifier.py) inspects each listing's year,
# power, gearbox and wording to decide whether it is *really* a V7 II.
SEARCH_TERM = "Moto Guzzi V7"

# Human readable label used in the dashboard title / headings.
TARGET_LABEL = "Moto Guzzi V7 II"

# --------------------------------------------------------------------------- #
# Optional filters (None / 0 means "no filter"). Applied AFTER classification.
# --------------------------------------------------------------------------- #
MIN_PRICE_EUR: int | None = None       # e.g. 4000
MAX_PRICE_EUR: int | None = None       # e.g. 9000
MIN_YEAR: int | None = None            # e.g. 2015 (further narrow first registration)
MAX_YEAR: int | None = None            # e.g. 2017

# Location filter for Kleinanzeigen (optional). Leave POSTAL_CODE empty to
# search all of Germany. RADIUS_KM is only used when POSTAL_CODE is set.
POSTAL_CODE: str = ""                  # e.g. "10115"
RADIUS_KM: int = 200

# --------------------------------------------------------------------------- #
# Classification behaviour
# --------------------------------------------------------------------------- #
# Only listings whose V7 II confidence is >= this value are stored/shown.
# Listings that are confidently a *different* model (V7 III, V7 850, Mk1) are
# always discarded regardless of this threshold.
MIN_STORE_CONFIDENCE = 0.35

# Confidence >= this is shown as a green "Confirmed" badge; between the store
# threshold and this value is shown as an amber "Likely / Uncertain" badge.
CONFIRMED_CONFIDENCE = 0.75

# --------------------------------------------------------------------------- #
# Dashboard behaviour
# --------------------------------------------------------------------------- #
# Listings first discovered within this many hours get the pulsing "NEW" badge.
NEW_LISTING_HOURS = 48

# Timezone used for the "last updated" stamp on the dashboard.
DISPLAY_TIMEZONE = "Europe/Berlin"

# --------------------------------------------------------------------------- #
# HTTP / scraping behaviour
# --------------------------------------------------------------------------- #
# Fetch each candidate's detail page to read year / power / description.
# This is what makes reliable V7 II detection possible, so keep it on.
FETCH_DETAIL_PAGES = True

# Be polite: cap how many *new* detail pages we fetch per site per run, and wait
# between requests. New listings are what matter, so already-known ones are not
# re-fetched — so in steady state a run makes only a handful of requests.
#
# These defaults are tuned to stay inside the ScraperAPI FREE tier
# (~1,000 requests/month). Rough budget: 2 runs/day x 30 days = 60 runs;
# each run ≈ (MAX_SEARCH_PAGES + a few new detail pages) x 2 sites. If you move
# to a paid plan you can safely raise MAX_SEARCH_PAGES to 3-5 and
# MAX_DETAIL_FETCHES_PER_SITE to 40+ for wider coverage.
MAX_DETAIL_FETCHES_PER_SITE = 15
REQUEST_DELAY_SECONDS = 2.0            # base delay between requests
REQUEST_JITTER_SECONDS = 1.5          # random extra delay (0..this) per request

# How many search result pages to walk per site (each page ≈ 25 listings).
MAX_SEARCH_PAGES = 2

# Retry / timeout behaviour for every HTTP request.
REQUEST_TIMEOUT = 30
MAX_RETRIES = 3
RETRY_BACKOFF_SECONDS = 4.0           # exponential: 4, 8, 16 ...

# Enable/disable individual sites without touching code elsewhere.
ENABLE_KLEINANZEIGEN = True
ENABLE_MOBILE_DE = True

# --------------------------------------------------------------------------- #
# Optional proxy / scraping service (driven by env vars — never hard-coded)
# --------------------------------------------------------------------------- #
# 1) ScraperAPI-style key. If set, every request is routed through ScraperAPI
#    with a German exit IP, which reliably defeats the datacenter-IP blocking
#    that GitHub Actions runners otherwise hit. Get a free key at scraperapi.com
#    and store it as the GitHub Actions secret SCRAPER_API_KEY.
SCRAPER_API_KEY = os.environ.get("SCRAPER_API_KEY", "").strip()
SCRAPER_API_ENDPOINT = "https://api.scraperapi.com/"
SCRAPER_API_COUNTRY = "de"            # request a German exit node

# 2) Alternatively, a generic HTTP(S) proxy URL, e.g.
#    http://user:pass@host:port . Used only when SCRAPER_API_KEY is empty.
PROXY_URL = os.environ.get("PROXY_URL", "").strip()

# A small pool of realistic desktop User-Agent strings; one is chosen per run.
USER_AGENTS = [
    ("Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
     "(KHTML, like Gecko) Chrome/125.0.0.0 Safari/537.36"),
    ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
     "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"),
    ("Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/605.1.15 "
     "(KHTML, like Gecko) Version/17.4 Safari/605.1.15"),
    ("Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:125.0) "
     "Gecko/20100101 Firefox/125.0"),
]


def proxy_mode() -> str:
    """Return the active proxy strategy: 'scraperapi', 'proxy' or 'direct'."""
    if SCRAPER_API_KEY:
        return "scraperapi"
    if PROXY_URL:
        return "proxy"
    return "direct"
