#!/usr/bin/env python3
"""
Minimum price and liquidity floors.

Every screening path (Finviz Elite, free web scrape, legacy scraper) must be
gated on the same floor so sub-$5 / illiquid names never reach a
recommendation.  The Finviz-side URL filters are a coarse first pass; the
runtime guard in :func:`filter_illiquid` is the authoritative enforcement and
runs regardless of which fetch path produced the rows.
"""

import logging
from typing import Any, Dict, Iterable, List, Optional, Sequence

logger = logging.getLogger(__name__)


# --- Thresholds (single source of truth) ------------------------------------

#: Reject anything trading below this price.
MIN_PRICE = 5.0

#: Reject anything whose average dollar volume is below this.
MIN_AVG_DOLLAR_VOLUME = 5_000_000.0

#: Finviz expresses average volume in thousands of shares.
MIN_AVG_VOLUME_THOUSANDS = 500

#: Finviz URL filter tokens matching the thresholds above.
FINVIZ_MIN_PRICE_FILTER = "sh_price_o5"
FINVIZ_MIN_AVG_VOLUME_FILTER = "sh_avgvol_o{}".format(MIN_AVG_VOLUME_THOUSANDS)

#: Finviz has no generic "between" syntax, only a fixed set of range tokens.
#: When a profile already caps price we swap the cap for the equivalent range
#: that also carries the $5 floor.  Caps with no $5-based range token (e.g.
#: ``sh_price_u100``) are left alone and rely on the runtime guard.
FINVIZ_PRICE_RANGE_WITH_FLOOR = {
    "sh_price_u10": "sh_price_5to10",
    "sh_price_u20": "sh_price_5to20",
    "sh_price_u50": "sh_price_5to50",
}


# --- Field access -----------------------------------------------------------

PRICE_KEYS = ("price", "last", "close", "close_price")
AVG_VOLUME_KEYS = ("avg_volume", "average_volume", "avg_vol", "avgvol")
VOLUME_KEYS = ("volume", "vol")

_SUFFIX_MULTIPLIERS = {"K": 1_000.0, "M": 1_000_000.0, "B": 1_000_000_000.0}


def coerce_number(value: Any) -> Optional[float]:
    """Coerce a Finviz-ish cell value to a float, or None if unparseable.

    Handles ``$``, thousands separators, percent signs and K/M/B suffixes.
    Returns None (never 0) for missing or malformed input so callers can tell
    "absent" apart from "genuinely zero".
    """
    if value is None:
        return None
    if isinstance(value, bool):
        return None
    if isinstance(value, (int, float)):
        return float(value)

    text = str(value).strip().replace(",", "").replace("$", "").replace("%", "")
    if not text or text in {"-", "--", "N/A", "n/a"}:
        return None

    multiplier = 1.0
    suffix = text[-1].upper()
    if suffix in _SUFFIX_MULTIPLIERS:
        multiplier = _SUFFIX_MULTIPLIERS[suffix]
        text = text[:-1]

    try:
        return float(text) * multiplier
    except ValueError:
        return None


def _first_present(stock: Dict[str, Any], keys: Sequence[str]) -> Optional[float]:
    for key in keys:
        if key in stock:
            parsed = coerce_number(stock[key])
            if parsed is not None:
                return parsed
    return None


def get_price(stock: Dict[str, Any]) -> Optional[float]:
    """Price for the row, or None when it is missing/unparseable."""
    return _first_present(stock, PRICE_KEYS)


def get_liquidity_volume(stock: Dict[str, Any]) -> Optional[float]:
    """Average share volume, falling back to the session volume."""
    avg = _first_present(stock, AVG_VOLUME_KEYS)
    if avg is not None:
        return avg
    return _first_present(stock, VOLUME_KEYS)


def average_dollar_volume(stock: Dict[str, Any]) -> Optional[float]:
    """Average dollar volume (price * average share volume)."""
    price = get_price(stock)
    volume = get_liquidity_volume(stock)
    if price is None or volume is None:
        return None
    return price * volume


# --- Runtime guard ----------------------------------------------------------

def check_liquidity(stock: Dict[str, Any]) -> Optional[str]:
    """Return None when the row clears the floors, else a rejection reason."""
    price = get_price(stock)
    if price is None:
        return "price missing or unparseable"
    if price <= 0:
        return "price is {:.4f} (non-positive)".format(price)
    if price < MIN_PRICE:
        return "price ${:.2f} below minimum ${:.2f}".format(price, MIN_PRICE)

    volume = get_liquidity_volume(stock)
    if volume is None:
        return "volume missing or unparseable"

    dollar_volume = price * volume
    if dollar_volume < MIN_AVG_DOLLAR_VOLUME:
        return "avg dollar volume ${:,.0f} below minimum ${:,.0f}".format(
            dollar_volume, MIN_AVG_DOLLAR_VOLUME
        )
    return None


def passes_liquidity_filters(stock: Dict[str, Any]) -> bool:
    """True when the row clears both the price and dollar-volume floors."""
    return check_liquidity(stock) is None


def filter_illiquid(stocks: Iterable[Dict[str, Any]],
                    context: str = "") -> List[Dict[str, Any]]:
    """Drop rows that fail the floors, logging each rejection."""
    label = " [{}]".format(context) if context else ""
    kept: List[Dict[str, Any]] = []
    dropped = 0

    for stock in stocks:
        reason = check_liquidity(stock)
        if reason is None:
            kept.append(stock)
            continue
        dropped += 1
        ticker = stock.get("ticker") or stock.get("symbol") or "?"
        logger.info("[LIQUIDITY]%s dropped %s: %s", label, ticker, reason)

    if dropped:
        logger.info(
            "[LIQUIDITY]%s kept %d of %d rows (min price $%.2f, min avg $vol $%s)",
            label, len(kept), len(kept) + dropped, MIN_PRICE,
            format(MIN_AVG_DOLLAR_VOLUME, ",.0f"),
        )
    return kept


# --- Finviz filter-token merging -------------------------------------------

def _avgvol_floor_thousands(token: str) -> Optional[int]:
    """Parse ``sh_avgvol_o750`` -> 750.  None when it is not an 'over' token."""
    suffix = token[len("sh_avgvol_"):]
    if not suffix.startswith("o"):
        return None
    try:
        return int(float(suffix[1:]))
    except ValueError:
        return None


def merge_liquidity_filters(filters: Sequence[str]) -> List[str]:
    """Apply the price / average-volume floors to a list of Finviz tokens.

    Existing tokens are kept when they are already at least as strict; a price
    cap is swapped for the equivalent floored range where Finviz has one.
    """
    merged: List[str] = []
    has_price = False
    has_avgvol = False

    for token in filters:
        token = token.strip()
        if not token:
            continue
        if token.startswith("sh_price_"):
            has_price = True
            merged.append(FINVIZ_PRICE_RANGE_WITH_FLOOR.get(token, token))
        elif token.startswith("sh_avgvol_"):
            has_avgvol = True
            floor = _avgvol_floor_thousands(token)
            if floor is not None and floor >= MIN_AVG_VOLUME_THOUSANDS:
                merged.append(token)
            else:
                merged.append(FINVIZ_MIN_AVG_VOLUME_FILTER)
        else:
            merged.append(token)

    if not has_price:
        merged.append(FINVIZ_MIN_PRICE_FILTER)
    if not has_avgvol:
        merged.append(FINVIZ_MIN_AVG_VOLUME_FILTER)

    # De-duplicate while preserving order.
    seen = set()
    deduped = []
    for token in merged:
        if token not in seen:
            seen.add(token)
            deduped.append(token)
    return deduped


def merge_liquidity_filter_string(filter_str: str) -> str:
    """Comma-separated variant of :func:`merge_liquidity_filters`."""
    tokens = [t for t in (filter_str or "").split(",") if t.strip()]
    return ",".join(merge_liquidity_filters(tokens))


def with_liquidity_filters(finviz_filters: Dict[str, Any]) -> Dict[str, Any]:
    """Profile-dict variant: ``{"sh_price_u20": True, ...}`` in and out."""
    plain = [key for key, value in finviz_filters.items() if value is True]
    other = {key: value for key, value in finviz_filters.items() if value is not True}

    merged: Dict[str, Any] = {token: True for token in merge_liquidity_filters(plain)}
    merged.update(other)
    return merged
