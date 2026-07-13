"""
Data model for a single marketplace listing plus (de)serialization helpers.

A ``Listing`` is deliberately a plain dataclass with primitive fields so that it
round-trips cleanly to/from ``listings.json`` without any custom JSON encoders.
"""

from __future__ import annotations

import hashlib
from dataclasses import asdict, dataclass, field
from typing import Any


@dataclass
class Classification:
    """Result of the V7 II detection logic for a listing."""

    is_v7ii: bool = False
    confidence: float = 0.0          # 0.0 .. 1.0
    category: str = "unknown"        # confirmed | likely | uncertain | rejected
    reasons: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict[str, Any] | None) -> "Classification":
        if not data:
            return cls()
        return cls(
            is_v7ii=bool(data.get("is_v7ii", False)),
            confidence=float(data.get("confidence", 0.0)),
            category=str(data.get("category", "unknown")),
            reasons=list(data.get("reasons", [])),
        )


@dataclass
class Listing:
    """A normalized listing shared across every marketplace scraper."""

    # Identity / provenance
    id: str                          # stable, unique across runs (source:native_id)
    source: str                      # "kleinanzeigen" | "mobile.de"
    url: str

    # Core advert content
    title: str = ""
    price_eur: int | None = None     # parsed integer price, None if "VB"/unknown
    price_raw: str = ""              # original price text, e.g. "6.500 € VB"
    mileage_km: int | None = None
    first_registration: str = ""     # "MM/YYYY" or "YYYY" as advertised
    year: int | None = None          # parsed 4-digit year from first_registration
    power_ps: int | None = None      # engine power in PS (metric hp)
    location: str = ""
    image_url: str = ""
    description: str = ""            # detail-page description text (truncated)

    # Bookkeeping (ISO-8601 UTC strings)
    date_found: str = ""            # first time we ever saw this listing
    last_seen: str = ""             # most recent run that still saw it

    # Classification
    classification: Classification = field(default_factory=Classification)

    # ---------------------------------------------------------------- #
    # Serialization
    # ---------------------------------------------------------------- #
    def to_dict(self) -> dict[str, Any]:
        data = asdict(self)
        data["classification"] = self.classification.to_dict()
        return data

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "Listing":
        data = dict(data)  # shallow copy so we don't mutate the caller's dict
        classification = Classification.from_dict(data.pop("classification", None))
        # Drop any unexpected keys so old JSON files stay forward-compatible.
        allowed = {f for f in cls.__dataclass_fields__ if f != "classification"}
        clean = {k: v for k, v in data.items() if k in allowed}
        return cls(classification=classification, **clean)


def make_listing_id(source: str, native_id: str | None, url: str) -> str:
    """
    Build a stable, unique id for a listing.

    Prefer the marketplace's own advert id; fall back to a short hash of the URL
    so listings without an obvious id are still deduplicated correctly.
    """
    if native_id:
        return f"{source}:{native_id}"
    digest = hashlib.sha1(url.encode("utf-8")).hexdigest()[:12]
    return f"{source}:{digest}"
