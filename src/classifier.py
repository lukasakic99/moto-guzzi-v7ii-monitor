"""
Moto Guzzi V7 II detection.

The title of a listing is unreliable — sellers write "V7", "V7 750", "V7 II",
"V7ii", or even mislabel a V7 III as a V7 II. This module looks at the *whole*
advert (title + description + parsed year + power) and produces a confidence
score plus human-readable reasons.

Reference facts used to distinguish the generations
---------------------------------------------------
Moto Guzzi V7 II  (the target, 2015 – mid 2017)
  * 744 cc air-cooled 90° V-twin ("small block")
  * 48 PS / 35 kW (full) or 34 PS / 25 kW (A2-restricted)
  * FIRST V7 with a 6-speed gearbox (Mk1 had 5 speeds)
  * FIRST V7 with standard ABS + traction control (MGCT)
  * Trims: Stone, Special, Racer, Stornello, Scrambler

V7 / V7 Mk1 (2008 – 2014)         -> 5-speed, no ABS, ~48–51 PS  (reject)
V7 III (mid 2017 – 2020)          -> 744 cc but 52 PS / 38 kW    (reject)
V7 850 / V7 IV / V7 Special 2021+ -> 853 cc, 65 PS               (reject)
"""

from __future__ import annotations

import re

import config
from .models import Classification, Listing

# --------------------------------------------------------------------------- #
# Regular expressions (case-insensitive, applied to a normalised text blob)
# --------------------------------------------------------------------------- #
# Explicit "second generation" markers. The negative lookahead/behind stop
# "v7 ii" from also matching inside "v7 iii".
RE_V7_II = re.compile(r"\bv\s*7\s*[- ]?\s*(?:ii|mk\s*2|mark\s*2|2)\b(?!\s*i)", re.I)
RE_V7_II_STRICT = re.compile(r"\bv\s*7\s*ii\b(?!i)", re.I)

# Other generations we want to actively reject.
RE_V7_III = re.compile(r"\bv\s*7\s*(?:iii|mk\s*3|mark\s*3|3)\b", re.I)
RE_V7_850 = re.compile(r"\bv\s*7\s*(?:850|iv|4|stone\s*850|special\s*850)\b", re.I)
RE_850CC = re.compile(r"\b8\s*5\s*3\s*(?:cc|ccm)?\b|\b850\s*(?:cc|ccm)\b", re.I)

# Displacement consistent with the small-block V7 (II and III share 744 cc).
RE_744CC = re.compile(r"\b7\s*4\s*4\s*(?:cc|ccm)?\b|\b750\s*(?:cc|ccm)?\b", re.I)

# Gearbox: 6-speed points to II/III, 5-speed points to the Mk1.
RE_SIX_SPEED = re.compile(r"6[- ]?(?:gang|speed|-?gang-?getriebe)", re.I)
RE_FIVE_SPEED = re.compile(r"5[- ]?(?:gang|speed|-?gang-?getriebe)", re.I)

# ABS / traction control were introduced with the V7 II.
RE_ABS = re.compile(r"\babs\b", re.I)
RE_TRACTION = re.compile(r"traktionskontrolle|traction control|mgct", re.I)

# A generic V7 mention (so we know it is at least the right family).
RE_V7_ANY = re.compile(r"\bv\s*7\b", re.I)
RE_MOTO_GUZZI = re.compile(r"moto\s*guzzi|guzzi", re.I)


def _normalise(text: str) -> str:
    """Lower-case and collapse whitespace so the regexes behave predictably."""
    return re.sub(r"\s+", " ", (text or "").lower())


def classify(listing: Listing) -> Classification:
    """
    Inspect a listing and return a :class:`Classification`.

    The score starts neutral and accumulates positive/negative evidence. Certain
    strong signals (an explicit other-generation match) force an immediate
    rejection regardless of everything else.
    """
    blob = _normalise(f"{listing.title} {listing.description}")
    reasons: list[str] = []
    score = 0.0

    # ------------------------------------------------------------------ #
    # 0. Sanity: is this even a Moto Guzzi V7 of some kind?
    # ------------------------------------------------------------------ #
    if not RE_V7_ANY.search(blob):
        return Classification(
            is_v7ii=False, confidence=0.0, category="rejected",
            reasons=["No 'V7' reference found in title or description."],
        )
    if not RE_MOTO_GUZZI.search(blob):
        reasons.append("No explicit 'Moto Guzzi' text (matched on 'V7' only).")

    # ------------------------------------------------------------------ #
    # 1. Hard rejections — clearly a different model
    # ------------------------------------------------------------------ #
    if RE_V7_850.search(blob) or RE_850CC.search(blob):
        return Classification(
            is_v7ii=False, confidence=0.0, category="rejected",
            reasons=["Mentions the 850 cc V7 (V7 850 / V7 IV) — not a V7 II."],
        )

    explicit_ii = bool(RE_V7_II.search(blob))
    explicit_iii = bool(RE_V7_III.search(blob))

    # If it says V7 III and NOT V7 II, reject. If it somehow says both, let the
    # scoring below sort it out but note the conflict.
    if explicit_iii and not explicit_ii:
        return Classification(
            is_v7ii=False, confidence=0.05, category="rejected",
            reasons=["Explicitly advertised as a V7 III (2017+, 52 PS)."],
        )

    # ------------------------------------------------------------------ #
    # 2. Positive / negative evidence
    # ------------------------------------------------------------------ #
    if RE_V7_II_STRICT.search(blob):
        score += 0.55
        reasons.append("Title/description explicitly says 'V7 II'.")
    elif explicit_ii:
        score += 0.45
        reasons.append("Contains a second-generation marker (V7 2 / Mk2).")
    else:
        reasons.append("No explicit 'II' — judging by year, power and equipment.")

    # First-registration year is the single strongest independent signal.
    year = listing.year
    if year is not None:
        if 2015 <= year <= 2016:
            score += 0.35
            reasons.append(f"First registration {year} is squarely V7 II era.")
        elif year == 2017:
            score += 0.10
            reasons.append("First registration 2017 overlaps V7 II and V7 III.")
        elif 2008 <= year <= 2014:
            score -= 0.45
            reasons.append(f"First registration {year} predates the V7 II (Mk1).")
        elif year >= 2018:
            score -= 0.55
            reasons.append(f"First registration {year} is after the V7 II (V7 III/850).")
    else:
        reasons.append("First-registration year unknown.")

    # Power. 48 PS / 35 kW (full) or 34 PS / 25 kW (A2) fit the V7 II. 52 PS is
    # the V7 III giveaway.
    ps = listing.power_ps
    if ps is not None:
        if ps in (47, 48, 49) or 34 <= ps <= 36 or ps == 50:
            score += 0.15
            reasons.append(f"{ps} PS matches the V7 II (48 PS, or 34 PS A2).")
        elif 51 <= ps <= 53:
            score -= 0.30
            reasons.append(f"{ps} PS matches the V7 III, not the V7 II.")
        elif ps >= 60:
            score -= 0.40
            reasons.append(f"{ps} PS is far above the V7 II (likely the 850).")

    # Displacement consistent with the small block.
    if RE_744CC.search(blob):
        score += 0.05
        reasons.append("Displacement (744/750 cc) consistent with the V7 II.")

    # Gearbox: 6-speed supports II/III, 5-speed points to the Mk1.
    if RE_SIX_SPEED.search(blob):
        score += 0.12
        reasons.append("6-speed gearbox — introduced on the V7 II (Mk1 had 5).")
    elif RE_FIVE_SPEED.search(blob):
        score -= 0.25
        reasons.append("5-speed gearbox suggests the earlier V7 Mk1.")

    # ABS / traction control were standard from the V7 II onward. Only meaningful
    # in combination with an in-range year (a retrofitted Mk1 is very unlikely).
    if (RE_ABS.search(blob) or RE_TRACTION.search(blob)) and (year is None or year >= 2015):
        score += 0.08
        reasons.append("ABS / traction control fitted (standard from the V7 II).")

    # ------------------------------------------------------------------ #
    # 3. Turn the score into a bounded confidence + category
    # ------------------------------------------------------------------ #
    confidence = max(0.0, min(1.0, score))

    if confidence >= config.CONFIRMED_CONFIDENCE:
        category = "confirmed"
    elif confidence >= config.MIN_STORE_CONFIDENCE:
        category = "likely" if confidence >= 0.55 else "uncertain"
    else:
        category = "rejected"

    return Classification(
        is_v7ii=confidence >= config.MIN_STORE_CONFIDENCE,
        confidence=round(confidence, 2),
        category=category,
        reasons=reasons,
    )
