"""
Persistence layer around ``listings.json`` (our tiny file-based "database").

Responsibilities
----------------
* Load existing listings (tolerant of a missing/empty/corrupt file).
* Merge freshly scraped listings into the store: keep the original
  ``date_found`` for known adverts, stamp new ones, refresh ``last_seen``.
* Keep the list sorted newest-first and write it back atomically.
"""

from __future__ import annotations

import json
import logging
import os
import tempfile
from datetime import datetime, timezone
from pathlib import Path

from .models import Listing

log = logging.getLogger("storage")


def utc_now_iso() -> str:
    """Current UTC time as an ISO-8601 string (second precision)."""
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def load_listings(path: Path) -> list[Listing]:
    """Read listings from disk. Returns an empty list if anything is off."""
    if not path.exists():
        log.info("No existing %s — starting a fresh database.", path.name)
        return []
    try:
        raw = json.loads(path.read_text(encoding="utf-8") or "[]")
    except (json.JSONDecodeError, OSError) as exc:
        log.error("Could not read %s (%s) — starting empty.", path.name, exc)
        return []
    listings = []
    for item in raw:
        try:
            listings.append(Listing.from_dict(item))
        except (TypeError, ValueError) as exc:
            log.warning("Skipping malformed listing record: %s", exc)
    log.info("Loaded %d existing listings from %s", len(listings), path.name)
    return listings


def save_listings(path: Path, listings: list[Listing]) -> None:
    """Write listings back to disk atomically (write-temp-then-rename)."""
    payload = json.dumps(
        [listing.to_dict() for listing in listings],
        ensure_ascii=False,
        indent=2,
    )
    # Atomic replace so a crash mid-write can never corrupt the database.
    fd, tmp = tempfile.mkstemp(dir=str(path.parent), suffix=".tmp")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            handle.write(payload)
        os.replace(tmp, path)
    finally:
        if os.path.exists(tmp):
            os.remove(tmp)
    log.info("Saved %d listings to %s", len(listings), path.name)


def merge_listings(
    existing: list[Listing],
    scraped: list[Listing],
) -> tuple[list[Listing], list[Listing]]:
    """
    Merge ``scraped`` into ``existing``.

    Returns ``(merged_sorted_newest_first, newly_discovered)``.

    * Brand-new listings are stamped with ``date_found``/``last_seen`` = now and
      appended.
    * Already-known listings keep their rich stored data (description, year,
      power, classification) — re-scrapes only fetch the lightweight card for
      known ids — and merely have ``last_seen`` refreshed plus a conservative
      price/image update when the fresh scrape provides one.
    """
    now = utc_now_iso()
    by_id: dict[str, Listing] = {listing.id: listing for listing in existing}
    newly_discovered: list[Listing] = []

    for fresh in scraped:
        prior = by_id.get(fresh.id)
        if prior is None:
            fresh.date_found = now
            fresh.last_seen = now
            by_id[fresh.id] = fresh
            newly_discovered.append(fresh)
        else:
            prior.last_seen = now
            if fresh.price_eur is not None:
                prior.price_eur = fresh.price_eur
                prior.price_raw = fresh.price_raw or prior.price_raw
            if fresh.image_url and not prior.image_url:
                prior.image_url = fresh.image_url

    merged = list(by_id.values())
    # Sort by discovery time, newest first. Ties fall back to id for stability.
    merged.sort(key=lambda l: (l.date_found, l.id), reverse=True)

    log.info("Merge complete: %d total, %d new this run.",
             len(merged), len(newly_discovered))
    return merged, newly_discovered
