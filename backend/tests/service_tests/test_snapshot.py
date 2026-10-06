"""Tests for ai/snapshot.py (the portfolio data sent to the LLM).

build_snapshot and the formatters are pure functions, so there is no
database and no network: holdings and closed transactions are built
directly as HoldingBase / ClosedTransaction with `holding()` and `sale()`,
and performance is a plain dict shaped like get_portfolio_performance's.
Expected numbers are calculated by hand and written in comments next to
the test.
"""

from datetime import datetime

import pytest
from pydantic import ValidationError

from ai.snapshot import PortfolioSnapshot, build_snapshot, format_money, format_percent
from db.schemas import ClosedTransaction, HoldingBase


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def holding(symbol, shares, cost, value=None):
    """Open position; value=None means the price lookup failed."""
    if value is None:
        return HoldingBase(
            symbol=symbol, number_current_shares=shares,
            avg_cost_per_share=cost / shares, cost_bases=cost,
        )
    gain = value - cost
    return HoldingBase(
        symbol=symbol, number_current_shares=shares,
        avg_cost_per_share=cost / shares, cost_bases=cost,
        current_price_per_share=value / shares, current_value=value,
        unrealized_gain_loss=gain, return_percentage=gain / cost * 100,
    )


def sale(symbol, shares, cost, proceeds):
    """One realized SELL."""
    gain = proceeds - cost
    return ClosedTransaction(
        transaction_date=datetime(2026, 1, 1), symbol=symbol,
        number_shares_sold=shares, avg_cost_per_share=cost / shares,
        sold_price_per_share=proceeds / shares,
        total_cost_of_shares_sold=cost, total_sold_price=proceeds,
        realized_gain_loss=gain, return_percentage=gain / cost * 100,
    )


# ---------------------------------------------------------------------------
# format_money / format_percent
# ---------------------------------------------------------------------------

def test_format_money_separators():
    # "," for thousands, "." for decimals, always 2 decimals.
    assert format_money(1234.5) == "1,234.50"
    assert format_money(1234567.891) == "1,234,567.89"
    assert format_money(0) == "0.00"


def test_format_money_signed():
    # Gains get "+", losses "-", zero no sign.
    assert format_money(500, signed=True) == "+500.00"
    assert format_money(-1000, signed=True) == "-1,000.00"
    assert format_money(0, signed=True) == "0.00"


def test_format_money_never_prints_minus_zero():
    # -0.001 rounds to -0.0, which must print as "0.00".
    assert format_money(-0.001, signed=True) == "0.00"


def test_format_percent():
    # One decimal and "%": 12.36 -> 12.4 ; -16.666 -> -16.7.
    assert format_percent(12.36) == "12.4%"
    assert format_percent(-16.666, signed=True) == "-16.7%"
    assert format_percent(-0.01, signed=True) == "0.0%"


# ---------------------------------------------------------------------------
# build_snapshot: positions and totals
# ---------------------------------------------------------------------------

def test_positions_allocation_and_totals():
    # AAPL: cost 1000, value 1500, gain +500 (+50%).
    # MSFT: cost 2000, value 1000, gain -1000 (-50%).
    # Total value 2500 -> AAPL 1500/2500 = 60%, MSFT 1000/2500 = 40%.
    # Total cost 3000, total gain -500 -> -500/3000 = -16.67% -> "-16.7%".
    snapshot = build_snapshot(
        [holding("MSFT", 5, 2000, 1000), holding("AAPL", 10, 1000, 1500)], [],
    )

    aapl, msft = snapshot.positions
    assert (aapl.symbol, aapl.allocation, aapl.unrealized_gain, aapl.unrealized_return) == (
        "AAPL", "60.0%", "+500.00", "+50.0%",
    )
    assert (msft.symbol, msft.allocation, msft.unrealized_gain, msft.unrealized_return) == (
        "MSFT", "40.0%", "-1,000.00", "-50.0%",
    )
    assert snapshot.total_value == "2,500.00"
    assert snapshot.total_cost == "3,000.00"
    assert snapshot.total_unrealized_gain == "-500.00"
    assert snapshot.total_unrealized_return == "-16.7%"


def test_positions_sorted_by_value_with_unpriced_last():
    # Largest value first (AAPL 1500 > MSFT 1000); positions without a
    # price go last, sorted by symbol.
    snapshot = build_snapshot(
        [holding("TSLA", 2, 400), holding("MSFT", 5, 2000, 1000),
         holding("AMZN", 1, 100), holding("AAPL", 10, 1000, 1500)],
        [],
    )

    assert [p.symbol for p in snapshot.positions] == ["AAPL", "MSFT", "AMZN", "TSLA"]


def test_position_without_price_is_marked_and_left_out_of_totals():
    # TSLA has no price: no value/allocation/gain, listed in
    # positions_without_price, and its cost (400) isn't in total_cost.
    # AAPL alone: value 1500 = 100% of the total, cost 1000.
    snapshot = build_snapshot([holding("AAPL", 10, 1000, 1500), holding("TSLA", 2, 400)], [])

    tsla = snapshot.positions[1]
    assert tsla.price_available is False
    assert tsla.cost_basis == "400.00"
    assert (tsla.current_value, tsla.allocation, tsla.unrealized_gain) == (None, None, None)
    assert snapshot.positions_without_price == ["TSLA"]
    assert snapshot.positions[0].allocation == "100.0%"
    assert snapshot.total_cost == "1,000.00"


def test_no_prices_at_all_leaves_totals_empty():
    # Every lookup failed: no totals instead of dividing by zero.
    snapshot = build_snapshot([holding("TSLA", 2, 400)], [])

    assert snapshot.total_value is None
    assert snapshot.total_unrealized_return is None
    assert snapshot.positions_without_price == ["TSLA"]


def test_empty_portfolio():
    # No holdings, no sales, no performance: empty lists and None totals.
    snapshot = build_snapshot([], [])

    assert snapshot.positions == []
    assert snapshot.total_value is None
    assert snapshot.realized == []
    assert snapshot.total_realized_gain is None
    assert snapshot.performance is None


# ---------------------------------------------------------------------------
# build_snapshot: realized gains
# ---------------------------------------------------------------------------

def test_realized_gains_added_up_per_symbol():
    # AAPL sale 1: 2 shares, cost 200, sold 300 -> +100.
    # AAPL sale 2: 3 shares, cost 300, sold 270 -> -30.
    # AAPL total: 5 shares, gain +70, cost 500 -> +14%.
    # MSFT: 1 share, cost 100, sold 150 -> +50 (+50%).
    # Total realized: 70 + 50 = +120.
    snapshot = build_snapshot(
        [],
        [sale("MSFT", 1, 100, 150), sale("AAPL", 2, 200, 300), sale("AAPL", 3, 300, 270)],
    )

    aapl, msft = snapshot.realized
    assert (aapl.symbol, aapl.shares_sold, aapl.realized_gain, aapl.realized_return) == (
        "AAPL", 5, "+70.00", "+14.0%",
    )
    assert (msft.symbol, msft.shares_sold, msft.realized_gain, msft.realized_return) == (
        "MSFT", 1, "+50.00", "+50.0%",
    )
    assert snapshot.total_realized_gain == "+120.00"


# ---------------------------------------------------------------------------
# build_snapshot: performance
# ---------------------------------------------------------------------------

def test_performance_keeps_last_return_of_the_series():
    # Only the final point matters: 12.345678 -> "+12.3%".
    performance = {
        "method": "daily_end_of_day_flow",
        "start_date": "2025-10-05", "end_date": "2026-10-05",
        "history_limited": True,
        "points": [
            {"date": "2025-10-05", "holdings_value": 100, "return_percentage": 5.0},
            {"date": "2026-10-05", "holdings_value": 112, "return_percentage": 12.345678},
        ],
    }

    snapshot = build_snapshot([], [], performance)

    assert snapshot.performance.model_dump() == {
        "start_date": "2025-10-05", "end_date": "2026-10-05",
        "return_percentage": "+12.3%", "history_limited": True,
    }


@pytest.mark.parametrize("performance", [None, {"method": "daily_end_of_day_flow", "points": []}])
def test_performance_missing_or_empty_is_none(performance):
    # Not available (service failed) or no points in the range.
    assert build_snapshot([], [], performance).performance is None


# ---------------------------------------------------------------------------
# Privacy: only the expected fields
# ---------------------------------------------------------------------------

def test_snapshot_has_only_the_expected_fields():
    # Guard: a new field must be added here on purpose. Nothing personal or
    # typed by the user (name, description, username, email, ids).
    assert set(PortfolioSnapshot.model_fields) == {
        "positions", "positions_without_price",
        "total_value", "total_cost", "total_unrealized_gain", "total_unrealized_return",
        "realized", "total_realized_gain", "performance",
    }


def test_snapshot_rejects_unknown_fields():
    # extra="forbid": passing e.g. the portfolio name is an error.
    with pytest.raises(ValidationError):
        PortfolioSnapshot(**build_snapshot([], []).model_dump(), name="Mi portafolio")
