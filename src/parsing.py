"""
Small, dependency-free text parsers shared by the scrapers.

German number formatting uses '.' as the thousands separator and ',' as the
decimal separator, so these helpers are written with that in mind.
"""

from __future__ import annotations

import re

_DIGITS = re.compile(r"\d[\d.\s]*")


def parse_price(text: str | None) -> int | None:
    """
    Extract an integer euro price from strings like '6.500 € VB' or 'VB'.

    Returns ``None`` for negotiable-only ('VB'), 'Zu verschenken' or unparsable
    values.
    """
    if not text:
        return None
    match = _DIGITS.search(text)
    if not match:
        return None
    digits = re.sub(r"[.\s]", "", match.group())
    try:
        value = int(digits)
    except ValueError:
        return None
    # Ignore absurd values (parsing noise); a real bike is not €7 or €7 000 000.
    return value if 100 <= value <= 200_000 else None


def parse_mileage(text: str | None) -> int | None:
    """Extract kilometres from '34.500 km', '34500 KM', etc."""
    if not text:
        return None
    match = re.search(r"(\d[\d.\s]*)\s*km", text, re.I)
    if not match:
        return None
    digits = re.sub(r"[.\s]", "", match.group(1))
    try:
        km = int(digits)
    except ValueError:
        return None
    return km if 0 <= km <= 500_000 else None


def parse_year(text: str | None) -> int | None:
    """
    Pull a 4-digit registration year (1990–2035) out of 'EZ 03/2016',
    '2016', 'Baujahr 2016', etc. Prefers the most recent plausible year.
    """
    if not text:
        return None
    years = [int(y) for y in re.findall(r"\b(19[9]\d|20[0-3]\d)\b", text)]
    plausible = [y for y in years if 1990 <= y <= 2035]
    return max(plausible) if plausible else None


def parse_first_registration(text: str | None) -> str:
    """
    Normalise a first-registration string to 'MM/YYYY' when possible, else the
    bare year, else ''.
    """
    if not text:
        return ""
    mm_yyyy = re.search(r"(0[1-9]|1[0-2])[/.\-](19\d\d|20\d\d)", text)
    if mm_yyyy:
        return f"{mm_yyyy.group(1)}/{mm_yyyy.group(2)}"
    year = parse_year(text)
    return str(year) if year else ""


def parse_power_ps(text: str | None) -> int | None:
    """
    Extract engine power in PS. Handles '48 PS', '35 kW', '35 kW (48 PS)'.

    When only kW is given it is converted to PS (1 kW ≈ 1.35962 PS).
    """
    if not text:
        return None
    ps = re.search(r"(\d{2,3})\s*ps\b", text, re.I)
    if ps:
        value = int(ps.group(1))
        if 5 <= value <= 250:
            return value
    kw = re.search(r"(\d{2,3})\s*kw\b", text, re.I)
    if kw:
        value = round(int(kw.group(1)) * 1.35962)
        if 5 <= value <= 250:
            return value
    return None
