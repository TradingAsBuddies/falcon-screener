#!/usr/bin/env python3
"""
Header-name based parsing of Finviz screener tables.

Finviz reorders and adds columns between views and layout revisions.  Parsing
by positional index (``cells[8]`` for price, ``cells[10]`` for volume) silently
produces price=0 / volume=0 the moment a column shifts, which is how a broken
scrape reaches the API as a real-looking quote.  This module resolves every
column by its header name and refuses to emit a row whose price or volume did
not parse.
"""

import logging
import re
from typing import Any, Dict, List, Optional, Sequence

logger = logging.getLogger(__name__)


class FinvizTableParseError(ValueError):
    """Raised when a Finviz table cannot be parsed safely."""


#: Output field -> accepted header spellings (normalised, lower-case).
COLUMN_ALIASES: Dict[str, Sequence[str]] = {
    "ticker": ("ticker", "symbol"),
    "company": ("company", "name"),
    "sector": ("sector",),
    "industry": ("industry",),
    "country": ("country",),
    "market_cap": ("market cap", "marketcap", "market capitalization"),
    "pe": ("p/e", "pe"),
    "price": ("price", "last", "last close", "close"),
    "change_pct": ("change", "change %", "chg", "% change"),
    "volume": ("volume", "vol"),
    "avg_volume": ("avg volume", "average volume", "avg vol", "avgvol"),
    "relative_volume": ("rel volume", "relative volume", "rvol"),
}

#: Fields a row must have for us to publish it.
REQUIRED_FIELDS = ("ticker", "price", "volume")

_VOLUME_SUFFIXES = {"K": 1_000, "M": 1_000_000, "B": 1_000_000_000}


def normalize_header(text: str) -> str:
    """Lower-case, collapse whitespace, drop trailing sort arrows."""
    cleaned = re.sub(r"\s+", " ", (text or "")).strip().lower()
    return cleaned.strip(" .▲▼↑↓")


def _resolve_header(table):
    """Return (field -> column index, header row element)."""
    header_row = None
    header_cells = []

    thead = table.find("thead")
    if thead is not None:
        header_row = thead.find("tr")
        if header_row is not None:
            header_cells = header_row.find_all(["th", "td"])

    if not header_cells:
        # Legacy layouts have no <thead>; the first row carries the labels,
        # sometimes as <td> rather than <th>.
        header_row = table.find("tr")
        if header_row is not None:
            header_cells = header_row.find_all("th") or header_row.find_all("td")

    if not header_cells:
        raise FinvizTableParseError("Finviz table has no header row")

    header_names = [normalize_header(cell.get_text()) for cell in header_cells]

    index: Dict[str, int] = {}
    for field, aliases in COLUMN_ALIASES.items():
        for position, name in enumerate(header_names):
            if name in aliases:
                index[field] = position
                break

    missing = [field for field in REQUIRED_FIELDS if field not in index]
    if missing:
        raise FinvizTableParseError(
            "Finviz table is missing required column(s) {} - headers were {}".format(
                ", ".join(missing), header_names
            )
        )

    return index, header_row


def build_header_index(table) -> Dict[str, int]:
    """Map output field name -> column index using the table's header row.

    Raises FinvizTableParseError when no header row is present or when the
    required price/volume/ticker columns cannot be located.
    """
    return _resolve_header(table)[0]


def parse_volume(vol_str: str) -> Optional[int]:
    """Parse a volume cell, returning None (never 0) when unparseable."""
    if vol_str is None:
        return None
    text = str(vol_str).strip().replace(",", "").upper()
    if not text or text in {"-", "--", "N/A"}:
        return None

    multiplier = 1
    if text[-1] in _VOLUME_SUFFIXES:
        multiplier = _VOLUME_SUFFIXES[text[-1]]
        text = text[:-1]

    try:
        return int(float(text) * multiplier)
    except ValueError:
        return None


def parse_price(price_str: str) -> Optional[float]:
    """Parse a price cell, returning None (never 0) when unparseable."""
    if price_str is None:
        return None
    text = str(price_str).strip().replace(",", "").replace("$", "")
    if not text or text in {"-", "--", "N/A"}:
        return None
    try:
        return float(text)
    except ValueError:
        return None


def parse_change_pct(change_str: str) -> Optional[float]:
    if change_str is None:
        return None
    text = str(change_str).strip().replace("%", "").replace(",", "").replace("+", "")
    if not text or text in {"-", "--", "N/A"}:
        return None
    try:
        return float(text)
    except ValueError:
        return None


def _cell_text(cells, index: Dict[str, int], field: str) -> str:
    position = index.get(field)
    if position is None or position >= len(cells):
        return ""
    return cells[position].get_text().strip()


def parse_screener_table(table, limit: Optional[int] = None,
                         on_error: str = "skip") -> List[Dict[str, Any]]:
    """Parse a Finviz screener table into row dicts, keyed by header name.

    Args:
        table: BeautifulSoup element for the screener table.
        limit: Maximum number of rows to return.
        on_error: ``"skip"`` logs an ERROR and drops an unparseable row;
            ``"raise"`` raises FinvizTableParseError instead.

    Returns:
        List of dicts. Every returned row has a ticker, a price > 0 and a
        parsed volume - a row that cannot supply those is never emitted.
    """
    if on_error not in {"skip", "raise"}:
        raise ValueError("on_error must be 'skip' or 'raise', got {!r}".format(on_error))

    index, header_row = _resolve_header(table)
    body = table.find("tbody") or table
    rows = body.find_all("tr")

    stocks: List[Dict[str, Any]] = []
    for row in rows:
        if row is header_row:
            continue  # a legacy header row built from <td> cells
        cells = row.find_all("td")
        if not cells:
            continue  # header row

        ticker = _cell_text(cells, index, "ticker")
        if not ticker:
            continue

        price = parse_price(_cell_text(cells, index, "price"))
        volume = parse_volume(_cell_text(cells, index, "volume"))

        problem = None
        if price is None:
            problem = "unparseable price {!r}".format(_cell_text(cells, index, "price"))
        elif price <= 0:
            problem = "non-positive price {!r}".format(price)
        elif volume is None:
            problem = "unparseable volume {!r}".format(_cell_text(cells, index, "volume"))

        if problem:
            message = "[FINVIZ] Dropping row for {}: {}".format(ticker, problem)
            if on_error == "raise":
                raise FinvizTableParseError(message)
            logger.error(message)
            continue

        stock: Dict[str, Any] = {
            "ticker": ticker,
            "company": _cell_text(cells, index, "company"),
            "sector": _cell_text(cells, index, "sector"),
            "industry": _cell_text(cells, index, "industry"),
            "market_cap": _cell_text(cells, index, "market_cap"),
            "price": price,
            "change_pct": parse_change_pct(_cell_text(cells, index, "change_pct")) or 0.0,
            "volume": volume,
        }

        if "avg_volume" in index:
            avg_volume = parse_volume(_cell_text(cells, index, "avg_volume"))
            if avg_volume is not None:
                stock["avg_volume"] = avg_volume

        stocks.append(stock)
        if limit is not None and len(stocks) >= limit:
            break

    return stocks


def parse_screener_html(html: str, limit: Optional[int] = None,
                        on_error: str = "skip") -> List[Dict[str, Any]]:
    """Convenience wrapper that locates the screener table inside an HTML page."""
    from bs4 import BeautifulSoup

    soup = BeautifulSoup(html, "html.parser")
    table = find_screener_table(soup)
    if table is None:
        raise FinvizTableParseError("Could not find a Finviz screener table")
    return parse_screener_table(table, limit=limit, on_error=on_error)


def find_screener_table(soup):
    """Locate the screener table across current and legacy Finviz layouts."""
    for finder in (
        lambda: soup.find("table", class_="screener_table"),
        lambda: soup.find("table", class_="styled-table-new"),
        lambda: soup.find("table", {"class": "table-light"}),
    ):
        table = finder()
        if table is not None:
            return table
    return None
