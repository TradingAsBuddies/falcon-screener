"""Header-name based Finviz parsing must survive a column reorder.

The bug this guards (TradingAsBuddies/falcon-screener#4): rows were read
positionally (cells[8]=Price, cells[9]=Change, cells[10]=Volume) with `else 0`
fallbacks, so a Finviz layout change silently published price=0 / volume=0.
"""

import logging

import pytest
from bs4 import BeautifulSoup

from conftest import load_screener_module

parser = load_screener_module("finviz_table_parser")


# The historical v=111 order the old index-based code assumed.
LEGACY_HEADERS = [
    "No.", "Ticker", "Company", "Sector", "Industry", "Country",
    "Market Cap", "P/E", "Price", "Change", "Volume",
]

# The same data with Volume/Price/Change moved and an extra column inserted -
# index 8 is now "Country" and index 10 is "P/E".
SHIFTED_HEADERS = [
    "No.", "Ticker", "Company", "Volume", "Price", "Change",
    "Sector", "Industry", "Country", "Market Cap", "P/E",
]

LEGACY_ROW = [
    "1", "AAPL", "Apple Inc.", "Technology", "Consumer Electronics", "USA",
    "3500.00B", "35.10", "231.40", "2.15%", "48,250,000",
]

SHIFTED_ROW = [
    "1", "AAPL", "Apple Inc.", "48,250,000", "231.40", "2.15%",
    "Technology", "Consumer Electronics", "USA", "3500.00B", "35.10",
]


def build_table(headers, rows, table_class="screener_table"):
    head = "".join("<th>{}</th>".format(h) for h in headers)
    body = "".join(
        "<tr>{}</tr>".format("".join("<td>{}</td>".format(c) for c in row))
        for row in rows
    )
    html = (
        '<table class="{cls}">'
        "<thead><tr>{head}</tr></thead>"
        "<tbody>{body}</tbody>"
        "</table>"
    ).format(cls=table_class, head=head, body=body)
    return BeautifulSoup(html, "html.parser").find("table")


def index_based_parse(table):
    """Reproduce the old positional parser, to prove it breaks on a shift."""
    row = table.find("tbody").find_all("tr")[0]
    cells = row.find_all("td")
    price_str = cells[8].text.strip()
    volume_str = cells[10].text.strip()
    try:
        price = float(price_str.replace(",", ""))
    except ValueError:
        price = 0
    try:
        volume = int(float(volume_str.replace(",", "")))
    except ValueError:
        volume = 0
    return price, volume


def test_parses_legacy_column_order():
    stocks = parser.parse_screener_table(build_table(LEGACY_HEADERS, [LEGACY_ROW]))

    assert len(stocks) == 1
    assert stocks[0]["ticker"] == "AAPL"
    assert stocks[0]["price"] == pytest.approx(231.40)
    assert stocks[0]["volume"] == 48_250_000
    assert stocks[0]["change_pct"] == pytest.approx(2.15)
    assert stocks[0]["sector"] == "Technology"


def test_index_based_parsing_would_have_published_garbage():
    """Guard the regression: positional parsing silently corrupts this row.

    On the shifted layout index 8 is Country ("USA") -> price falls through the
    `else 0` branch and publishes $0.00, while index 10 is P/E ("35.10") -> a
    P/E ratio is published as the share volume.
    """
    price, volume = index_based_parse(build_table(SHIFTED_HEADERS, [SHIFTED_ROW]))

    assert price == 0            # a $0 price reaching the API
    assert volume == 35          # the P/E column, not 48,250,000
    assert volume != 48_250_000


def test_index_based_parsing_zeroes_volume_when_the_shifted_cell_is_text():
    """The other half of the same bug: a non-numeric cell becomes volume 0."""
    headers = list(SHIFTED_HEADERS)
    row = list(SHIFTED_ROW)
    headers[10], row[10] = "Country", "USA"

    price, volume = index_based_parse(build_table(headers, [row]))

    assert price == 0
    assert volume == 0


def test_header_based_parsing_survives_the_same_shift():
    stocks = parser.parse_screener_table(build_table(SHIFTED_HEADERS, [SHIFTED_ROW]))

    assert len(stocks) == 1
    assert stocks[0]["ticker"] == "AAPL"
    assert stocks[0]["price"] == pytest.approx(231.40)
    assert stocks[0]["volume"] == 48_250_000
    assert stocks[0]["change_pct"] == pytest.approx(2.15)
    assert stocks[0]["sector"] == "Technology"


def test_headers_are_matched_case_and_whitespace_insensitively():
    headers = ["No.", " TICKER ", "Company", "Sector", "Industry", "Country",
               "Market  Cap", "P/E", "  price", "Change", "VOLUME "]
    stocks = parser.parse_screener_table(build_table(headers, [LEGACY_ROW]))

    assert stocks[0]["price"] == pytest.approx(231.40)
    assert stocks[0]["volume"] == 48_250_000


def test_avg_volume_column_is_captured_when_present():
    headers = LEGACY_HEADERS + ["Avg Volume"]
    stocks = parser.parse_screener_table(build_table(headers, [LEGACY_ROW + ["12.5M"]]))

    assert stocks[0]["avg_volume"] == 12_500_000


def test_unparseable_price_is_skipped_with_an_error_log(caplog):
    bad = list(LEGACY_ROW)
    bad[8] = "-"

    with caplog.at_level(logging.ERROR):
        stocks = parser.parse_screener_table(build_table(LEGACY_HEADERS, [bad]))

    assert stocks == []
    assert any("unparseable price" in r.message for r in caplog.records)


def test_zero_price_is_never_published(caplog):
    bad = list(LEGACY_ROW)
    bad[8] = "0.00"

    with caplog.at_level(logging.ERROR):
        stocks = parser.parse_screener_table(build_table(LEGACY_HEADERS, [bad]))

    assert stocks == []


def test_unparseable_volume_is_skipped():
    bad = list(LEGACY_ROW)
    bad[10] = "-"

    assert parser.parse_screener_table(build_table(LEGACY_HEADERS, [bad])) == []


def test_on_error_raise_propagates():
    bad = list(LEGACY_ROW)
    bad[8] = "n/a"

    with pytest.raises(parser.FinvizTableParseError):
        parser.parse_screener_table(build_table(LEGACY_HEADERS, [bad]), on_error="raise")


def test_good_rows_survive_a_bad_neighbour():
    bad = list(LEGACY_ROW)
    bad[1], bad[8] = "BADX", "-"

    stocks = parser.parse_screener_table(build_table(LEGACY_HEADERS, [bad, LEGACY_ROW]))

    assert [s["ticker"] for s in stocks] == ["AAPL"]


def test_missing_required_column_raises_rather_than_guessing():
    headers = [h for h in LEGACY_HEADERS if h != "Price"]
    row = [c for i, c in enumerate(LEGACY_ROW) if i != 8]

    with pytest.raises(parser.FinvizTableParseError) as excinfo:
        parser.parse_screener_table(build_table(headers, [row]))

    assert "price" in str(excinfo.value)


def test_limit_is_respected():
    rows = []
    for i, ticker in enumerate(["AAA", "BBB", "CCC"], start=1):
        row = list(LEGACY_ROW)
        row[0], row[1] = str(i), ticker
        rows.append(row)

    stocks = parser.parse_screener_table(build_table(LEGACY_HEADERS, rows), limit=2)

    assert [s["ticker"] for s in stocks] == ["AAA", "BBB"]


def test_parse_screener_html_finds_the_table_across_layouts():
    for table_class in ("screener_table", "styled-table-new", "table-light"):
        table = build_table(LEGACY_HEADERS, [LEGACY_ROW], table_class=table_class)
        stocks = parser.parse_screener_html(str(table))
        assert stocks[0]["ticker"] == "AAPL", table_class


def test_volume_suffixes():
    assert parser.parse_volume("1,234,567") == 1_234_567
    assert parser.parse_volume("48.25M") == 48_250_000
    assert parser.parse_volume("750K") == 750_000
    assert parser.parse_volume("1.2B") == 1_200_000_000
    assert parser.parse_volume("-") is None
    assert parser.parse_volume("") is None
    assert parser.parse_volume("abc") is None


def build_legacy_td_header_table(headers, rows):
    """No <thead>, header row built from <td> - the old table-light layout."""
    all_rows = [headers] + rows
    body = "".join(
        "<tr>{}</tr>".format("".join("<td>{}</td>".format(c) for c in row))
        for row in all_rows
    )
    html = '<table class="table-light">{}</table>'.format(body)
    return BeautifulSoup(html, "html.parser").find("table")


def test_legacy_td_header_row_is_not_parsed_as_data(caplog):
    table = build_legacy_td_header_table(LEGACY_HEADERS, [LEGACY_ROW])

    with caplog.at_level(logging.ERROR):
        stocks = parser.parse_screener_table(table)

    assert [s["ticker"] for s in stocks] == ["AAPL"]
    assert caplog.records == []
