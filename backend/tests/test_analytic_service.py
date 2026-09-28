"""Tests for services/analytic_service.py.

No database and no network: the transactions and both kinds of prices are
mocked, and fake transactions are plain objects built with `tx()`. The
holdings replay (HoldingService.build_holdings_dictionary) is the real one,
so the distribution tests also check the average-cost accounting.

Expected numbers are calculated by hand and written in comments next to the
test. Most of the tests are for _build_performance_series, where the return
math lives; the public performance methods only get the checks they add on
top (date validation, grouping per stock).
"""

from datetime import date, datetime, timedelta
from types import SimpleNamespace

import pandas as pd
import pytest
from fastapi import HTTPException

from models.models import TransactionType
from services.analytic_service import AnalyticService


# ---------------------------------------------------------------------------
# Helpers and fixtures
# ---------------------------------------------------------------------------

def tx(id, symbol, side, qty, price, day):
    """Fake transaction with the attributes the service reads."""
    return SimpleNamespace(
        id=id,
        symbol=symbol,
        transaction_type=side,
        quantity_actions=qty,
        price=price,
        total_value=qty * price,
        transaction_date=datetime.fromisoformat(day),
    )


def closes(prices_by_day):
    """Close prices indexed by date, like get_historical_stock_prices returns."""
    return pd.Series(
        list(prices_by_day.values()),
        index=pd.to_datetime(list(prices_by_day)),
    )


def returns(result):
    """Cumulative return (%) of each day in a performance result."""
    return [point["return_percentage"] for point in result["points"]]


def values(result):
    """Market value of the holdings on each day in a performance result."""
    return [point["holdings_value"] for point in result["points"]]


# 2026-01-05 is a Monday, 2026-01-09 a Friday.
MON, TUE, WED = date(2026, 1, 5), date(2026, 1, 6), date(2026, 1, 7)


@pytest.fixture
def service():
    """No session needed: the only database call is mocked by `transactions`."""
    return AnalyticService(session=None)


@pytest.fixture
def transactions(service, mocker):
    """Replaces the database query. Set return_value to the list of fake
    transactions (already sorted by date, like the real query), or
    side_effect to an HTTPException."""
    return mocker.patch.object(service.holding_service, "get_portfolio_transactions")


# The price functions are patched in analytic_service, not in
# market_data_service, because analytic_service imported them by name.

@pytest.fixture
def current_price(mocker):
    """Fake current price: return_value for one price, side_effect with a
    function for a different price per symbol."""
    return mocker.patch("services.analytic_service.get_current_stock_price")


@pytest.fixture
def historical_prices(mocker):
    """Fake price history: a `closes(...)` Series, or a function of
    (symbol, start, end) when there are several symbols."""
    return mocker.patch("services.analytic_service.get_historical_stock_prices")


# ---------------------------------------------------------------------------
# Shared by both distribution methods
# ---------------------------------------------------------------------------

DISTRIBUTION_METHODS = [
    "get_portfolio_distribution",
    "get_portfolio_unrealized_gains_distribution",
]


@pytest.mark.parametrize("method", DISTRIBUTION_METHODS)
async def test_distribution_price_failure_raises(service, transactions, current_price, method):
    transactions.return_value = [tx(1, "A", "BUY", 10, 100.0, "2026-01-05")]
    current_price.side_effect = ValueError("No price")

    with pytest.raises(ValueError):
        await getattr(service, method)(user_id=1, portfolio_id=1)


@pytest.mark.parametrize("method", DISTRIBUTION_METHODS)
async def test_distribution_portfolio_not_found(service, transactions, method):
    transactions.side_effect = HTTPException(status_code=404)

    with pytest.raises(HTTPException) as error:
        await getattr(service, method)(user_id=1, portfolio_id=1)
    assert error.value.status_code == 404


@pytest.mark.parametrize("method", DISTRIBUTION_METHODS)
async def test_distribution_oversell_in_history(service, transactions, method):
    transactions.return_value = [tx(1, "A", "SELL", 5, 100.0, "2026-01-05")]

    with pytest.raises(HTTPException) as error:
        await getattr(service, method)(user_id=1, portfolio_id=1)
    assert error.value.status_code == 400


# ---------------------------------------------------------------------------
# get_portfolio_distribution
# ---------------------------------------------------------------------------

async def test_distribution_single_stock(service, transactions, current_price):
    transactions.return_value = [tx(1, "A", "BUY", 10, 40.0, "2026-01-05")]
    current_price.return_value = 50.0

    total, distribution = await service.get_portfolio_distribution(user_id=1, portfolio_id=1)

    assert total == pytest.approx(500.0)
    assert distribution == {
        "A": {"current_value": pytest.approx(500.0), "distribution_percentage": pytest.approx(100.0)},
    }


async def test_distribution_two_stocks(service, transactions, current_price):
    transactions.return_value = [
        tx(1, "A", "BUY", 10, 25.0, "2026-01-05"),
        tx(2, "B", "BUY", 7, 90.0, "2026-01-05"),
    ]
    current_price.side_effect = lambda symbol: {"A": 30.0, "B": 100.0}[symbol]

    total, distribution = await service.get_portfolio_distribution(user_id=1, portfolio_id=1)

    assert total == pytest.approx(1000.0)  # 10*30 + 7*100
    assert distribution["A"]["current_value"] == pytest.approx(300.0)
    assert distribution["B"]["current_value"] == pytest.approx(700.0)
    assert distribution["A"]["distribution_percentage"] == pytest.approx(30.0)
    assert distribution["B"]["distribution_percentage"] == pytest.approx(70.0)


async def test_distribution_uses_shares_left_after_partial_sell(service, transactions, current_price):
    transactions.return_value = [
        tx(1, "A", "BUY", 10, 40.0, "2026-01-05"),
        tx(2, "A", "SELL", 4, 45.0, "2026-01-06"),
    ]
    current_price.return_value = 50.0

    total, _ = await service.get_portfolio_distribution(user_id=1, portfolio_id=1)

    assert total == pytest.approx(300.0)  # 6 shares * 50


async def test_distribution_skips_fully_sold_stock(service, transactions, current_price):
    transactions.return_value = [
        tx(1, "A", "BUY", 10, 40.0, "2026-01-05"),
        tx(2, "A", "SELL", 10, 45.0, "2026-01-06"),
        tx(3, "B", "BUY", 5, 20.0, "2026-01-06"),
    ]
    current_price.return_value = 20.0

    _, distribution = await service.get_portfolio_distribution(user_id=1, portfolio_id=1)

    assert list(distribution) == ["B"]
    current_price.assert_called_once_with("B")


async def test_distribution_empty_portfolio(service, transactions, current_price):
    transactions.return_value = []

    result = await service.get_portfolio_distribution(user_id=1, portfolio_id=1)

    assert result == (0.0, {})
    current_price.assert_not_called()


# ---------------------------------------------------------------------------
# get_portfolio_unrealized_gains_distribution
# ---------------------------------------------------------------------------

@pytest.mark.parametrize(
    "price, expected",
    [
        (120.0, 200.0),   # gain: 10*120 - 1000
        (80.0, -200.0),   # loss: 10*80 - 1000
    ],
)
async def test_unrealized_gain_or_loss(service, transactions, current_price, price, expected):
    transactions.return_value = [tx(1, "A", "BUY", 10, 100.0, "2026-01-05")]
    current_price.return_value = price

    result = await service.get_portfolio_unrealized_gains_distribution(user_id=1, portfolio_id=1)

    assert result == {"A": {"unrealized_gain_loss": pytest.approx(expected)}}


async def test_unrealized_uses_average_cost_after_partial_sell(service, transactions, current_price):
    # Average cost 110 (cost 2200 for 20 shares). Selling 5 removes 550,
    # leaving 15 shares with cost 1650. At 130: 15*130 - 1650 = 300.
    transactions.return_value = [
        tx(1, "A", "BUY", 10, 100.0, "2026-01-05"),
        tx(2, "A", "BUY", 10, 120.0, "2026-01-06"),
        tx(3, "A", "SELL", 5, 125.0, "2026-01-07"),
    ]
    current_price.return_value = 130.0

    result = await service.get_portfolio_unrealized_gains_distribution(user_id=1, portfolio_id=1)

    assert result["A"]["unrealized_gain_loss"] == pytest.approx(300.0)


async def test_unrealized_several_stocks(service, transactions, current_price):
    transactions.return_value = [
        tx(1, "A", "BUY", 10, 10.0, "2026-01-05"),
        tx(2, "B", "BUY", 2, 50.0, "2026-01-05"),
    ]
    current_price.side_effect = lambda symbol: {"A": 12.0, "B": 40.0}[symbol]

    result = await service.get_portfolio_unrealized_gains_distribution(user_id=1, portfolio_id=1)

    assert result == {
        "A": {"unrealized_gain_loss": pytest.approx(20.0)},    # 120 - 100
        "B": {"unrealized_gain_loss": pytest.approx(-20.0)},   # 80 - 100
    }


async def test_unrealized_skips_fully_sold_stock(service, transactions, current_price):
    transactions.return_value = [
        tx(1, "A", "BUY", 10, 40.0, "2026-01-05"),
        tx(2, "A", "SELL", 10, 45.0, "2026-01-06"),
        tx(3, "B", "BUY", 5, 20.0, "2026-01-06"),
    ]
    current_price.return_value = 25.0

    result = await service.get_portfolio_unrealized_gains_distribution(user_id=1, portfolio_id=1)

    assert list(result) == ["B"]


async def test_unrealized_empty_portfolio(service, transactions, current_price):
    transactions.return_value = []

    result = await service.get_portfolio_unrealized_gains_distribution(user_id=1, portfolio_id=1)

    assert result == {}
    current_price.assert_not_called()


# ---------------------------------------------------------------------------
# _build_performance_series
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("side", ["BUY", TransactionType.BUY])
async def test_first_day_return_includes_gap_to_close(service, historical_prices, side):
    historical_prices.return_value = closes({"2026-01-05": 110.0})
    txs = [tx(1, "A", side, 10, 100.0, "2026-01-05")]

    result = await service._build_performance_series(txs, MON, MON)

    assert result["points"] == [
        {"date": "2026-01-05", "holdings_value": pytest.approx(1100.0), "return_percentage": pytest.approx(10.0)},
    ]
    assert result["method"] == "daily_end_of_day_flow"
    assert result["start_date"] == "2026-01-05"
    assert result["end_date"] == "2026-01-05"
    assert result["provisional"] is False


async def test_returns_are_chained(service, historical_prices):
    historical_prices.return_value = closes({"2026-01-05": 110.0, "2026-01-06": 121.0})
    txs = [tx(1, "A", "BUY", 10, 100.0, "2026-01-05")]

    result = await service._build_performance_series(txs, MON, TUE)

    assert returns(result) == pytest.approx([10.0, 21.0])  # 1.1 * 1.1, not 10 + 10


async def test_buying_more_is_not_counted_as_gain(service, historical_prices):
    # Day 2: value 2300, flow 1150 -> factor (2300 - 1150) / 1100.
    # Cumulative 1.1 * 1150/1100 = 1.15, the same as the price move 100 -> 115.
    historical_prices.return_value = closes({"2026-01-05": 110.0, "2026-01-06": 115.0})
    txs = [
        tx(1, "A", "BUY", 10, 100.0, "2026-01-05"),
        tx(2, "A", "BUY", 10, 115.0, "2026-01-06"),
    ]

    result = await service._build_performance_series(txs, MON, TUE)

    assert values(result) == pytest.approx([1100.0, 2300.0])
    assert returns(result) == pytest.approx([10.0, 15.0])


async def test_selling_is_not_counted_as_loss(service, historical_prices):
    # Day 2: value 605, flow -605 -> factor (605 + 605) / 1100 = 1.1.
    historical_prices.return_value = closes({"2026-01-05": 110.0, "2026-01-06": 121.0})
    txs = [
        tx(1, "A", "BUY", 10, 100.0, "2026-01-05"),
        tx(2, "A", "SELL", 5, 121.0, "2026-01-06"),
    ]

    result = await service._build_performance_series(txs, MON, TUE)

    assert values(result) == pytest.approx([1100.0, 605.0])
    assert returns(result) == pytest.approx([10.0, 21.0])


async def test_weekend_uses_friday_close(service, historical_prices):
    historical_prices.return_value = closes({"2026-01-09": 110.0, "2026-01-12": 121.0})
    txs = [tx(1, "A", "BUY", 10, 100.0, "2026-01-09")]

    result = await service._build_performance_series(txs, date(2026, 1, 9), date(2026, 1, 12))

    assert [point["date"] for point in result["points"]] == [
        "2026-01-09", "2026-01-10", "2026-01-11", "2026-01-12",
    ]
    assert values(result) == pytest.approx([1100.0, 1100.0, 1100.0, 1210.0])
    assert returns(result) == pytest.approx([10.0, 10.0, 10.0, 21.0])


async def test_start_before_first_transaction_is_history_limited(service, historical_prices):
    historical_prices.return_value = closes({"2026-01-07": 110.0})
    txs = [tx(1, "A", "BUY", 10, 100.0, "2026-01-07")]

    result = await service._build_performance_series(txs, MON, WED)

    assert result["history_limited"] is True
    assert result["requested_start_date"] == "2026-01-05"
    assert result["start_date"] == "2026-01-07"
    assert len(result["points"]) == 1


async def test_start_after_first_transaction_starts_at_zero(service, historical_prices):
    historical_prices.return_value = closes(
        {"2026-01-05": 110.0, "2026-01-06": 121.0, "2026-01-07": 133.1}
    )
    txs = [tx(1, "A", "BUY", 10, 100.0, "2026-01-05")]

    result = await service._build_performance_series(txs, TUE, WED)

    assert result["history_limited"] is False
    assert values(result) == pytest.approx([1210.0, 1331.0])  # earlier buy sets the shares
    assert returns(result) == pytest.approx([0.0, 10.0])


async def test_transactions_after_end_date_are_ignored(service, historical_prices):
    historical_prices.return_value = closes({"2026-01-05": 110.0, "2026-01-06": 110.0})
    txs = [
        tx(1, "A", "BUY", 10, 100.0, "2026-01-05"),
        tx(2, "A", "BUY", 50, 100.0, "2026-01-06"),
    ]

    result = await service._build_performance_series(txs, MON, MON)

    assert values(result) == pytest.approx([1100.0])


@pytest.mark.parametrize(
    "txs",
    [
        [],
        [tx(1, "A", "BUY", 10, 100.0, "2026-01-10")],  # only after end_date
    ],
)
async def test_no_transactions_in_range_returns_no_points(service, historical_prices, txs):
    result = await service._build_performance_series(txs, MON, WED)

    assert result == {"method": "daily_end_of_day_flow", "points": []}
    historical_prices.assert_not_called()


async def test_end_date_today_is_provisional(service, historical_prices):
    today = date.today()
    historical_prices.return_value = closes({today.isoformat(): 110.0})
    txs = [tx(1, "A", "BUY", 10, 100.0, today.isoformat())]

    result = await service._build_performance_series(txs, today, today)

    assert result["provisional"] is True


async def test_price_dates_show_last_real_close_of_held_symbols(service, historical_prices):
    # A has no Monday close (forward-filled from Friday). B is sold on Monday.
    historical_prices.side_effect = lambda symbol, start, end: {
        "A": closes({"2026-01-09": 110.0}),
        "B": closes({"2026-01-09": 100.0, "2026-01-12": 110.0}),
    }[symbol]
    txs = [
        tx(1, "A", "BUY", 10, 100.0, "2026-01-09"),
        tx(2, "B", "BUY", 5, 100.0, "2026-01-09"),
        tx(3, "B", "SELL", 5, 110.0, "2026-01-12"),
    ]

    result = await service._build_performance_series(txs, date(2026, 1, 9), date(2026, 1, 12))

    assert result["price_dates"] == {"A": "2026-01-09"}


async def test_same_day_transactions_are_applied_by_id(service, historical_prices):
    historical_prices.return_value = closes({"2026-01-05": 110.0})
    txs = [  # given out of order on purpose: the sell only works after the buy
        tx(2, "A", "SELL", 4, 110.0, "2026-01-05"),
        tx(1, "A", "BUY", 10, 100.0, "2026-01-05"),
    ]

    result = await service._build_performance_series(txs, MON, MON)

    assert values(result) == pytest.approx([660.0])  # 6 shares * 110


@pytest.mark.parametrize(
    "txs, price, message",
    [
        (
            [tx(1, "A", "SELL", 5, 100.0, "2026-01-05")],
            100.0,
            "Negative holdings",
        ),
        (
            [tx(1, "A", "BUY", 10, 100.0, "2026-01-05")],
            float("nan"),
            "Missing valid price",
        ),
        (
            [
                tx(1, "A", "BUY", 10, 100.0, "2026-01-05"),
                tx(2, "A", "SELL", 10, 150.0, "2026-01-05"),
            ],
            100.0,
            "positive net investment",
        ),
        (
            [
                tx(1, "A", "BUY", 10, 100.0, "2026-01-05"),
                tx(2, "A", "BUY", 10, 500.0, "2026-01-06"),  # far above the close
            ],
            100.0,
            "unsuitable",
        ),
        (
            [
                tx(1, "A", "BUY", 10, 100.0, "2026-01-05"),
                tx(2, "A", "SELL", 10, 100.0, "2026-01-06"),
                tx(3, "A", "BUY", 10, 100.0, "2026-01-07"),
            ],
            100.0,
            "restarting an empty portfolio",
        ),
        (
            [tx(1, "A", "HOLD", 10, 100.0, "2026-01-05")],
            100.0,
            "Unsupported transaction type",
        ),
    ],
    ids=["oversell", "missing-price", "no-initial-investment",
         "bad-daily-factor", "restart", "unknown-type"],
)
async def test_performance_series_errors(service, historical_prices, txs, price, message):
    historical_prices.return_value = closes(
        {"2026-01-05": price, "2026-01-06": price, "2026-01-07": price}
    )

    with pytest.raises(ValueError, match=message):
        await service._build_performance_series(txs, MON, WED)


# ---------------------------------------------------------------------------
# get_portfolio_performance and get_stock_performances
# ---------------------------------------------------------------------------

PERFORMANCE_METHODS = ["get_portfolio_performance", "get_stock_performances"]


@pytest.mark.parametrize("method", PERFORMANCE_METHODS)
@pytest.mark.parametrize(
    "start, end",
    [
        (WED, MON),                                                # start after end
        (date.today(), date.today() + timedelta(days=1)),          # end in the future
    ],
    ids=["start-after-end", "end-in-future"],
)
async def test_invalid_date_range_raises_before_loading(service, transactions, method, start, end):
    with pytest.raises(ValueError, match="start <= end"):
        await getattr(service, method)(user_id=1, portfolio_id=1, start_date=start, end_date=end)

    transactions.assert_not_called()


async def test_portfolio_performance(service, transactions, historical_prices):
    transactions.return_value = [tx(1, "A", "BUY", 10, 100.0, "2026-01-05")]
    historical_prices.return_value = closes({"2026-01-05": 110.0, "2026-01-06": 121.0})

    result = await service.get_portfolio_performance(
        user_id=1, portfolio_id=2, start_date=MON, end_date=TUE,
    )

    assert returns(result) == pytest.approx([10.0, 21.0])
    transactions.assert_awaited_once_with(portfolio_id=2, user_id=1)


async def test_portfolio_performance_not_found(service, transactions):
    transactions.side_effect = HTTPException(status_code=404)

    with pytest.raises(HTTPException) as error:
        await service.get_portfolio_performance(
            user_id=1, portfolio_id=1, start_date=MON, end_date=TUE,
        )
    assert error.value.status_code == 404


async def test_stock_performances_one_series_per_stock(service, transactions, historical_prices):
    transactions.return_value = [
        tx(1, "B", "BUY", 5, 200.0, "2026-01-05"),
        tx(2, "A", "BUY", 10, 100.0, "2026-01-05"),
    ]
    historical_prices.side_effect = lambda symbol, start, end: {
        "A": closes({"2026-01-05": 110.0}),
        "B": closes({"2026-01-05": 180.0}),
    }[symbol]

    result = await service.get_stock_performances(
        user_id=1, portfolio_id=1, start_date=MON, end_date=MON,
    )

    assert list(result["stocks"]) == ["A", "B"]  # alphabetical
    assert returns(result["stocks"]["A"]) == pytest.approx([10.0])
    assert returns(result["stocks"]["B"]) == pytest.approx([-10.0])
    assert result["errors"] == {}
    assert result["method"] == "daily_end_of_day_flow"
    assert result["requested_start_date"] == "2026-01-05"
    assert result["end_date"] == "2026-01-05"


async def test_stock_performances_failing_stock_goes_to_errors(service, transactions, historical_prices):
    transactions.return_value = [
        tx(1, "A", "BUY", 10, 100.0, "2026-01-05"),
        tx(2, "B", "BUY", 5, 200.0, "2026-01-05"),
    ]
    historical_prices.side_effect = lambda symbol, start, end: {
        "A": closes({"2026-01-05": 110.0}),
        "B": closes({"2026-01-05": float("nan")}),
    }[symbol]

    result = await service.get_stock_performances(
        user_id=1, portfolio_id=1, start_date=MON, end_date=MON,
    )

    assert list(result["stocks"]) == ["A"]
    assert list(result["errors"]) == ["B"]
    assert "Missing valid price" in result["errors"]["B"]


async def test_stock_performances_skips_stock_not_held_in_window(service, transactions, historical_prices):
    # A is bought and fully sold before the window starts.
    transactions.return_value = [
        tx(1, "A", "BUY", 10, 100.0, "2026-01-05"),
        tx(2, "A", "SELL", 10, 100.0, "2026-01-06"),
        tx(3, "B", "BUY", 5, 100.0, "2026-01-05"),
    ]
    historical_prices.return_value = closes(
        {"2026-01-05": 100.0, "2026-01-06": 100.0, "2026-01-07": 100.0, "2026-01-08": 100.0}
    )

    result = await service.get_stock_performances(
        user_id=1, portfolio_id=1, start_date=WED, end_date=date(2026, 1, 8),
    )

    assert list(result["stocks"]) == ["B"]
    assert result["errors"] == {}


async def test_stock_performances_empty_portfolio(service, transactions, historical_prices):
    transactions.return_value = []

    result = await service.get_stock_performances(
        user_id=1, portfolio_id=1, start_date=MON, end_date=TUE,
    )

    assert result["stocks"] == {}
    assert result["errors"] == {}
    
    
    
