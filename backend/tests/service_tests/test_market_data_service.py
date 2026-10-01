"""Tests for services/market_data_service.py.

yfinance is never called: the `history` fixture replaces yf.Ticker, so each
test decides what the price history looks like and no network is needed.

Every function in the module wraps its errors in a generic ValueError
("Could not verify a usable price for ...") raised `from` the original
error. The specific reason is therefore checked on `error.value.__cause__`,
not on the ValueError itself.
"""

import pytest

import pandas as pd

from services.market_data_service import (
    get_current_stock_price,
    get_historical_stock_prices,
    ticker_validation,
)




# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture
def history(mocker):
    """Mock of yf.Ticker(...).history. Set its return_value to a DataFrame,
    or its side_effect to an exception, to fake what yfinance returns."""
    fake_stock = mocker.patch("services.market_data_service.yf.Ticker").return_value
    fake_history = fake_stock.history
    return fake_history


# ---------------------------------------------------------------------------
# get_current_stock_price
# ---------------------------------------------------------------------------

# The last close is None, so the price is the last valid one (105.0).
# The ticker is stripped and uppercased before the lookup.
def test_get_last_valid_close_price(history):
    history.return_value = pd.DataFrame({"Close": [101.0, 105.0, None]})
    assert get_current_stock_price(" apple ") == 105.0
    
# Each kind of unusable history gives its own reason in __cause__:
# no data at all, no Close column, only missing closes, zero or infinite price.
@pytest.mark.parametrize(
    "df, expected_cause",
    [
        (pd.DataFrame(), "No price history"),
        (pd.DataFrame({"Open": [1.0]}), "No price history"),
        (pd.DataFrame({"Close": [None]}), "No usable closing prices"),
        (pd.DataFrame({"Close": [0.0]}), "Invalid price"),
        (pd.DataFrame({"Close": [float("inf")]}), "Invalid price"),
    ]
)
def test_bad_history_raises(history, df, expected_cause):
    history.return_value = df

    with pytest.raises(ValueError) as error:
        get_current_stock_price("AAPL")
    assert str(error.value.__cause__) == expected_cause
    
# A blank ticker is rejected before yfinance is called, so no fixture is needed.
def test_empty_ticker():
    with pytest.raises(ValueError) as error:
        get_current_stock_price(" ")
    assert str(error.value.__cause__) == "Empty ticker"
    
      
# get_historical_stock_prices: an empty history for the window raises, with the
# symbol in the reason.
@pytest.mark.parametrize(
    "symbol, df, start_date, end_date, expected_outcome",
    [
        ("APPL", pd.DataFrame(), "2020-05-20", "2021-05-20", "No historical prices available for APPL")
    ]
)   
def test_bad_history_raises_historical(history, symbol, df, start_date, end_date, expected_outcome):
    history.return_value = df
    with pytest.raises(ValueError) as error:
        get_historical_stock_prices(symbol, start_date, end_date)
    assert str(error.value.__cause__) == expected_outcome


# get_current_stock_price: yfinance/network errors must come out as ValueError,
# the only error callers catch. The original error is kept as __cause__.
def test_network_error_raises_value_error(history):
    history.side_effect = ConnectionError("boom")

    with pytest.raises(ValueError) as error:
        get_current_stock_price("AAPL")
    assert isinstance(error.value.__cause__, ConnectionError)
    assert str(error.value.__cause__) == "boom"


# ---------------------------------------------------------------------------
# get_historical_stock_prices
# ---------------------------------------------------------------------------

def test_historical_prices_indexed_by_plain_date(history):
    # yfinance returns tz-aware timestamps; the function should reduce them to dates
    index = pd.date_range("2024-01-02", periods=3, tz="America/New_York")
    history.return_value = pd.DataFrame({"Close": [100.0, 101.5, 99.0]}, index=index)

    result = get_historical_stock_prices("AAPL", "2024-01-02", "2024-01-05")

    assert result.tolist() == [100.0, 101.5, 99.0]
    # Compare as Timestamps: the index resolution (s vs us) is a pandas detail, not behaviour
    assert list(result.index) == [
        pd.Timestamp("2024-01-02"),
        pd.Timestamp("2024-01-03"),
        pd.Timestamp("2024-01-04"),
    ]
    assert result.index.tz is None


# ---------------------------------------------------------------------------
# ticker_validation
# ---------------------------------------------------------------------------

# It only wraps get_current_stock_price: True when a price is found, False
# (not an exception) when the lookup fails.
def test_ticker_validation_true_for_usable_price(history):
    history.return_value = pd.DataFrame({"Close": [150.0]})
    assert ticker_validation("AAPL") is True


def test_ticker_validation_false_when_lookup_fails(history):
    history.return_value = pd.DataFrame()
    assert ticker_validation("AAPL") is False
