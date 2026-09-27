import pytest

import pandas as pd

from app.services.market_data_service import (
    get_current_stock_price,
    get_historical_stock_prices,
    ticker_validation,
)




@pytest.fixture
def history(mocker):
    fake_stock = mocker.patch("app.services.market_data_service.yf.Ticker").return_value
    fake_history = fake_stock.history
    return fake_history


# From services.market_data_service.get_current_stock_price
def test_get_last_valid_close_price(history):
    history.return_value = pd.DataFrame({"Close": [101.0, 105.0, None]})
    assert get_current_stock_price(" apple ") == 105.0
    
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
    
def test_empty_ticker():
    with pytest.raises(ValueError) as error:
        get_current_stock_price(" ")
    assert str(error.value.__cause__) == "Empty ticker"
    
      
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


# yfinance/network errors must come out as ValueError, the only error callers catch
def test_network_error_raises_value_error(history):
    history.side_effect = ConnectionError("boom")

    with pytest.raises(ValueError) as error:
        get_current_stock_price("AAPL")
    assert isinstance(error.value.__cause__, ConnectionError)
    assert str(error.value.__cause__) == "boom"


# From services.market_data_service.get_historical_stock_prices
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


# From services.market_data_service.ticker_validation
def test_ticker_validation_true_for_usable_price(history):
    history.return_value = pd.DataFrame({"Close": [150.0]})
    assert ticker_validation("AAPL") is True


def test_ticker_validation_false_when_lookup_fails(history):
    history.return_value = pd.DataFrame()
    assert ticker_validation("AAPL") is False
