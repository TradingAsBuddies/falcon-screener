"""Sector and capitalisation carried from the screen onto each recommendation.

The AI path returns only what the model wrote, so sector and market cap were
dropped. The trader then had nothing to classify a name with, and every symbol
routed to the default strategy (falcon-trader#46).
"""

import pytest

from falcon_screener.multi_screener import MultiScreener


def _attach(recs, stocks):
    screener = MultiScreener.__new__(MultiScreener)   # no DB, no API keys
    return screener._attach_screened_facts(recs, stocks)


STOCK = {"ticker": "NKE", "sector": "Consumer Cyclical", "industry": "Footwear",
         "market_cap": "48.50B", "price": 33.87, "avg_volume": 27824210.0}


def test_sector_and_capitalisation_are_carried():
    recs = _attach([{"ticker": "NKE", "confidence_score": 7}], [STOCK])
    assert recs[0]["sector"] == "Consumer Cyclical"
    assert recs[0]["market_cap"] == "48.50B"
    assert recs[0]["avg_volume"] == 27824210.0


def test_the_screened_price_is_recorded_separately():
    """The trader re-fetches a live price; this dates the recommendation."""
    recs = _attach([{"ticker": "NKE"}], [STOCK])
    assert recs[0]["screened_price"] == 33.87


def test_matching_is_case_insensitive():
    assert _attach([{"ticker": "nke"}], [STOCK])[0]["sector"] == "Consumer Cyclical"


def test_symbol_is_accepted_in_place_of_ticker():
    assert _attach([{"symbol": "NKE"}], [STOCK])[0]["sector"] == "Consumer Cyclical"


def test_a_value_the_model_already_supplied_is_not_overwritten():
    recs = _attach([{"ticker": "NKE", "sector": "Model Said This"}], [STOCK])
    assert recs[0]["sector"] == "Model Said This"


def test_a_name_absent_from_the_screen_is_left_alone():
    """The model occasionally names something that was not screened."""
    assert "sector" not in _attach([{"ticker": "TSLA"}], [STOCK])[0]


def test_empty_values_in_the_screen_are_not_copied():
    recs = _attach([{"ticker": "NKE"}], [{"ticker": "NKE", "sector": "", "market_cap": None}])
    assert "sector" not in recs[0] and "market_cap" not in recs[0]


@pytest.mark.parametrize("recs", [None, []])
def test_no_recommendations_is_an_empty_list(recs):
    assert _attach(recs, [STOCK]) == []


@pytest.mark.parametrize("stocks", [None, []])
def test_no_screened_rows_leaves_recommendations_untouched(stocks):
    assert _attach([{"ticker": "NKE"}], stocks) == [{"ticker": "NKE"}]


def test_non_dict_entries_do_not_raise():
    assert _attach(["junk", {"ticker": "NKE"}], [STOCK])[1]["sector"] == "Consumer Cyclical"


def test_the_first_row_for_a_ticker_wins():
    duplicate = dict(STOCK, sector="Second Row")
    assert _attach([{"ticker": "NKE"}], [STOCK, duplicate])[0]["sector"] == "Consumer Cyclical"


def test_carried_fields_are_the_ones_the_trader_needs():
    assert set(MultiScreener.CARRIED_FIELDS) >= {"sector", "market_cap"}


def test_market_cap_in_dollars_is_carried_alongside_the_raw_cell():
    """Finviz's cell is in millions; the trader classifies on the dollars."""
    stock = dict(STOCK, market_cap="48500.00", market_cap_usd=4.85e10)
    recs = _attach([{"ticker": "NKE"}], [stock])
    assert recs[0]["market_cap"] == "48500.00"
    assert recs[0]["market_cap_usd"] == 4.85e10


def test_the_dollar_field_is_in_the_carried_set():
    assert "market_cap_usd" in MultiScreener.CARRIED_FIELDS
