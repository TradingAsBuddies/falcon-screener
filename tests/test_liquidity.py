"""Minimum price / liquidity floors (TradingAsBuddies/falcon-screener#4).

The live screener recommended SNYR ($0.13), AEON ($0.30), JZ ($0.90) and
BRNX ($2.38) because profiles only ever set UPPER price bounds.
"""

import logging

import pytest

from conftest import load_screener_module

liquidity = load_screener_module("liquidity")


# Tickers taken from the bug report, with plausible volumes.
PENNY_STOCKS = [
    {"ticker": "SNYR", "price": 0.13, "volume": 30_000_000},
    {"ticker": "AEON", "price": 0.30, "volume": 12_000_000},
    {"ticker": "JZ", "price": 0.90, "volume": 5_000_000},
    {"ticker": "BRNX", "price": 2.38, "volume": 4_000_000},
]

LIQUID_STOCK = {"ticker": "AAPL", "price": 231.40, "volume": 48_250_000}


def test_thresholds_are_named_constants():
    assert liquidity.MIN_PRICE == 5.0
    assert liquidity.MIN_AVG_DOLLAR_VOLUME == 5_000_000.0


@pytest.mark.parametrize("stock", PENNY_STOCKS, ids=lambda s: s["ticker"])
def test_reported_penny_stocks_are_rejected(stock):
    assert not liquidity.passes_liquidity_filters(stock)
    assert "below minimum" in liquidity.check_liquidity(stock)


def test_liquid_stock_passes():
    assert liquidity.passes_liquidity_filters(LIQUID_STOCK)
    assert liquidity.check_liquidity(LIQUID_STOCK) is None


def test_price_exactly_at_the_floor_passes():
    assert liquidity.passes_liquidity_filters(
        {"ticker": "EDGE", "price": 5.0, "volume": 2_000_000}
    )


def test_price_just_below_the_floor_is_rejected():
    assert not liquidity.passes_liquidity_filters(
        {"ticker": "EDGE", "price": 4.99, "volume": 2_000_000}
    )


def test_thin_dollar_volume_is_rejected_even_above_the_price_floor():
    # $50 x 50,000 shares = $2.5M, under the $5M floor.
    stock = {"ticker": "THIN", "price": 50.0, "volume": 50_000}

    assert not liquidity.passes_liquidity_filters(stock)
    assert "avg dollar volume" in liquidity.check_liquidity(stock)


def test_dollar_volume_exactly_at_the_floor_passes():
    assert liquidity.passes_liquidity_filters(
        {"ticker": "EDGE", "price": 10.0, "volume": 500_000}
    )


def test_average_volume_is_preferred_over_session_volume():
    # A one-day volume spike must not rescue a normally illiquid name.
    stock = {"ticker": "SPIKE", "price": 10.0, "volume": 9_000_000,
             "avg_volume": 100_000}

    assert liquidity.average_dollar_volume(stock) == pytest.approx(1_000_000.0)
    assert not liquidity.passes_liquidity_filters(stock)


def test_missing_price_is_rejected_not_defaulted_to_zero():
    assert liquidity.get_price({"ticker": "X", "price": "-"}) is None
    assert not liquidity.passes_liquidity_filters({"ticker": "X", "volume": 1_000_000})


def test_zero_price_is_rejected():
    assert not liquidity.passes_liquidity_filters(
        {"ticker": "ZERO", "price": 0, "volume": 9_000_000}
    )


def test_missing_volume_is_rejected():
    assert not liquidity.passes_liquidity_filters({"ticker": "X", "price": 50.0})


def test_string_cells_are_coerced():
    stock = {"ticker": "STR", "price": "$231.40", "volume": "48.25M"}

    assert liquidity.passes_liquidity_filters(stock)
    assert liquidity.get_price(stock) == pytest.approx(231.40)
    assert liquidity.get_liquidity_volume(stock) == pytest.approx(48_250_000)


def test_filter_illiquid_drops_only_the_failures(caplog):
    rows = PENNY_STOCKS + [LIQUID_STOCK]

    with caplog.at_level(logging.INFO):
        kept = liquidity.filter_illiquid(rows, context="unit test")

    assert [s["ticker"] for s in kept] == ["AAPL"]
    logged = [r.getMessage() for r in caplog.records]
    assert any("SNYR" in line and "below minimum" in line for line in logged)


def test_filter_illiquid_is_a_noop_for_clean_input():
    assert liquidity.filter_illiquid([LIQUID_STOCK]) == [LIQUID_STOCK]


# --- Finviz filter tokens ---------------------------------------------------

def test_gainers_fallback_filter_gains_price_and_volume_floors():
    # daily_report.get_top_gainers_today previously sent only sh_avgvol_o200.
    merged = liquidity.merge_liquidity_filter_string("sh_avgvol_o200")

    assert "sh_price_o5" in merged
    assert "sh_avgvol_o500" in merged
    assert "sh_avgvol_o200" not in merged


def test_empty_filter_string_still_gets_both_floors():
    assert set(liquidity.merge_liquidity_filter_string("").split(",")) == {
        "sh_price_o5", "sh_avgvol_o500",
    }


def test_price_cap_becomes_a_floored_range():
    merged = liquidity.merge_liquidity_filters(["sh_price_u20", "ta_change_u"])

    assert merged == ["sh_price_5to20", "ta_change_u", "sh_avgvol_o500"]


def test_stricter_existing_volume_floor_is_kept():
    merged = liquidity.merge_liquidity_filters(["sh_avgvol_o750", "sh_price_u50"])

    assert "sh_avgvol_o750" in merged
    assert "sh_avgvol_o500" not in merged
    assert "sh_price_5to50" in merged


def test_unrelated_filters_are_preserved():
    merged = liquidity.merge_liquidity_filters(["cap_midover", "earningsdate_thisweek"])

    assert "cap_midover" in merged
    assert "earningsdate_thisweek" in merged


def test_merging_is_idempotent():
    once = liquidity.merge_liquidity_filters(["sh_avgvol_o200", "sh_price_u20"])

    assert liquidity.merge_liquidity_filters(once) == once


def test_profile_dict_form_applies_the_floors():
    profile_filters = {
        "sh_avgvol_o750": True,
        "sh_price_u20": True,
        "sh_relvol_o1.5": True,
        "ta_change_u": True,
    }

    merged = liquidity.with_liquidity_filters(profile_filters)

    assert "sh_price_5to20" in merged
    assert "sh_price_u20" not in merged
    assert merged["sh_relvol_o1.5"] is True
