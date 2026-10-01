"""Tests for services/position_accounting_service.py.

Pure functions, so there is nothing to mock: no database, no network. Fake
transactions are plain objects built with `tx()`, and `replay()` applies a
list of them to a new Position, the way the callers do for one symbol.

Expected numbers use the average cost method and are calculated by hand in
the comments next to each test.
"""

from datetime import datetime
from types import SimpleNamespace

import pytest

from models.models import TransactionType
from services.position_accounting_service import Position, apply_transaction


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

DAY = datetime(2026, 1, 5)


def tx(side, qty, price, symbol="A"):
    """Fake transaction with the attributes apply_transaction reads."""
    return SimpleNamespace(
        symbol=symbol,
        transaction_type=side,
        quantity_actions=qty,
        price=price,
        transaction_date=DAY,
    )


def replay(*transactions):
    """Apply the transactions in order to a new Position.

    Returns the position and the list of results (None for each BUY, the
    realized-sale dict for each SELL).
    """
    position = Position()
    results = [apply_transaction(position, transaction) for transaction in transactions]
    return position, results


# ---------------------------------------------------------------------------
# Position
# ---------------------------------------------------------------------------

# An empty position has no average cost, and must not divide by zero.
def test_new_position_is_empty():
    position = Position()

    assert position.shares == 0
    assert position.cost_basis == 0.0
    assert position.average_cost == 0.0


def test_average_cost_is_cost_per_held_share():
    assert Position(shares=4, cost_basis=500.0).average_cost == pytest.approx(125.0)


# ---------------------------------------------------------------------------
# apply_transaction: BUY
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("side", ["BUY", TransactionType.BUY])
def test_buy_adds_shares_and_cost(side):
    position, results = replay(tx(side, 10, 100.0))

    assert results == [None]
    assert position.shares == 10
    assert position.cost_basis == pytest.approx(1000.0)


def test_buys_average_their_prices():
    # 10*100 + 10*120 = 2200 for 20 shares -> average 110.
    position, _ = replay(tx("BUY", 10, 100.0), tx("BUY", 10, 120.0))

    assert position.shares == 20
    assert position.cost_basis == pytest.approx(2200.0)
    assert position.average_cost == pytest.approx(110.0)


# ---------------------------------------------------------------------------
# apply_transaction: SELL
# ---------------------------------------------------------------------------

def test_partial_sell_realizes_gain_at_average_cost():
    # Average cost 110. Selling 5 at 130: cost 550, proceeds 650, gain 100,
    # return 100 / 550 = 18.18%.
    sell = tx("SELL", 5, 130.0)
    position, results = replay(tx("BUY", 10, 100.0), tx("BUY", 10, 120.0), sell)

    assert results[-1] == {
        "transaction_date": DAY,
        "symbol": "A",
        "number_shares_sold": 5,
        "avg_cost_per_share": pytest.approx(110.0),
        "sold_price_per_share": 130.0,
        "total_cost_of_shares_sold": pytest.approx(550.0),
        "total_sold_price": pytest.approx(650.0),
        "realized_gain_loss": pytest.approx(100.0),
        "return_percentage": pytest.approx(100 / 550 * 100),
    }


def test_partial_sell_keeps_average_cost():
    # 15 shares left with cost 2200 - 550 = 1650: still 110 per share.
    position, _ = replay(tx("BUY", 10, 100.0), tx("BUY", 10, 120.0), tx("SELL", 5, 130.0))

    assert position.shares == 15
    assert position.cost_basis == pytest.approx(1650.0)
    assert position.average_cost == pytest.approx(110.0)


def test_sell_below_average_cost_realizes_loss():
    # Cost 4*100 = 400, proceeds 4*80 = 320: loss 80, return -20%.
    _, results = replay(tx("BUY", 10, 100.0), tx("SELL", 4, 80.0))

    assert results[-1]["realized_gain_loss"] == pytest.approx(-80.0)
    assert results[-1]["return_percentage"] == pytest.approx(-20.0)


@pytest.mark.parametrize("side", ["SELL", TransactionType.SELL])
def test_sell_accepts_enum_or_string(side):
    position, results = replay(tx("BUY", 10, 100.0), tx(side, 10, 100.0))

    assert position.shares == 0
    assert results[-1]["number_shares_sold"] == 10


def test_selling_everything_resets_cost_basis_exactly():
    # These numbers leave -1.4e-14 of float residue without the reset.
    position, _ = replay(
        tx("BUY", 3, 10.1),
        tx("BUY", 7, 20.3),
        tx("SELL", 4, 25.0),
        tx("SELL", 6, 25.0),
    )

    assert position.shares == 0
    assert position.cost_basis == 0.0  # exact, not approx


def test_buy_after_selling_everything_starts_clean():
    # The earlier average (100) must not leak into the new position.
    position, _ = replay(tx("BUY", 10, 100.0), tx("SELL", 10, 150.0), tx("BUY", 5, 50.0))

    assert position.shares == 5
    assert position.average_cost == pytest.approx(50.0)


def test_sell_of_free_shares_has_zero_return_percentage():
    # Shares bought at 0 have no cost, so the return can't be a percentage
    # of it. It is 0.0 instead of a division by zero.
    _, results = replay(tx("BUY", 10, 0.0), tx("SELL", 5, 10.0))

    assert results[-1]["realized_gain_loss"] == pytest.approx(50.0)
    assert results[-1]["return_percentage"] == 0.0


# ---------------------------------------------------------------------------
# apply_transaction: errors
# ---------------------------------------------------------------------------

@pytest.mark.parametrize(
    "transactions, message",
    [
        ([tx("BUY", 0, 100.0)], "must be positive"),
        ([tx("BUY", -5, 100.0)], "must be positive"),
        ([tx("SELL", 0, 100.0)], "must be positive"),
        ([tx("HOLD", 10, 100.0)], "Unsupported transaction type"),
        ([tx("SELL", 1, 100.0)], "Not enough shares to sell for A"),
        ([tx("BUY", 5, 100.0), tx("SELL", 6, 100.0)], "Not enough shares to sell for A"),
    ],
    ids=["zero-buy", "negative-buy", "zero-sell", "unknown-type",
         "sell-without-shares", "oversell"],
)
def test_invalid_transactions_raise(transactions, message):
    with pytest.raises(ValueError, match=message):
        replay(*transactions)


# A rejected transaction must leave the position as it was, so callers can
# report the error without a half-applied state.
@pytest.mark.parametrize(
    "transaction",
    [tx("SELL", 6, 100.0), tx("BUY", 0, 100.0), tx("HOLD", 1, 100.0)],
    ids=["oversell", "zero-quantity", "unknown-type"],
)
def test_rejected_transaction_leaves_position_unchanged(transaction):
    position, _ = replay(tx("BUY", 5, 100.0))

    with pytest.raises(ValueError):
        apply_transaction(position, transaction)

    assert position == Position(shares=5, cost_basis=500.0)
