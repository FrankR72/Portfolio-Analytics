"""Tests for services/holding_service.py (open positions with live prices).

Two kinds of tests, depending on what each method does:

- get_portfolio_transactions and summarize_holdings run queries (ownership
  check, ordering by date then id), so they use a real database: a fresh
  in-memory SQLite per test, like test_user_service.py.
- build_holdings_dictionary and enrich_holdings_with_current_prices are pure
  logic, so they get plain fake transactions built with `tx()` and holding
  dicts built with `holding()`, and never touch the database.

The current price is always mocked, so nothing calls yfinance. Expected
numbers are calculated by hand and written in comments next to the test.
"""

from datetime import datetime
from types import SimpleNamespace

import pytest
from fastapi import HTTPException
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from db.schemas import HoldingBase
from models import models
from services.holding_service import HoldingService


# ---------------------------------------------------------------------------
# Fixtures and helpers
# ---------------------------------------------------------------------------

@pytest.fixture
async def session():
    """Session on a new, empty in-memory database with all tables created."""
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as conn:
        await conn.run_sync(models.Base.metadata.create_all)
    async with async_sessionmaker(engine, expire_on_commit=False)() as s:
        yield s
    await engine.dispose()


@pytest.fixture
def service(session):
    return HoldingService(session)


@pytest.fixture
async def owner(session):
    user = models.User(username="Geralt", email="geralt@example.com", hashed_password="x")
    session.add(user)
    await session.commit()
    return user


@pytest.fixture
async def stranger(session):
    """A second user, to check that one user can't read another's portfolio."""
    user = models.User(username="Yennefer", email="yennefer@example.com", hashed_password="x")
    session.add(user)
    await session.commit()
    return user


@pytest.fixture
async def portfolio(session, owner):
    portfolio = models.Portfolio(name="Main", user_id=owner.id)
    session.add(portfolio)
    await session.commit()
    return portfolio


async def add_tx(session, portfolio, symbol, side, qty, price, day):
    """Insert a transaction in the database. Ids follow the insertion order."""
    transaction = models.Transaction(
        symbol=symbol,
        transaction_type=models.TransactionType(side),
        quantity_actions=qty,
        price=price,
        total_value=qty * price,
        transaction_date=datetime.fromisoformat(day),
        portfolio_id=portfolio.id,
    )
    session.add(transaction)
    await session.commit()
    return transaction


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


def holding(symbol, shares, cost_basis):
    """One entry as build_holdings_dictionary returns it."""
    return {
        "symbol": symbol,
        "number_current_shares": shares,
        "avg_cost_per_share": cost_basis / shares if shares else 0.0,
        "cost_bases": cost_basis,
    }


# Patched in holding_service, not in market_data_service, because
# holding_service imported it by name.
@pytest.fixture
def current_price(mocker):
    """Fake current price: return_value for one price, side_effect with a
    function for a different price per symbol."""
    return mocker.patch("services.holding_service.get_current_stock_price")

# Uses closure
def prices(by_symbol):
    """side_effect for `current_price`: a price per symbol, and ValueError
    (like the real function) for a symbol that isn't listed."""
    def lookup(symbol):
        if symbol not in by_symbol:
            raise ValueError(f"No price for {symbol}")
        return by_symbol[symbol]
    return lookup


# ---------------------------------------------------------------------------
# get_portfolio_transactions
# ---------------------------------------------------------------------------

# Ordered by date, and by id for transactions on the same date, whatever the
# insertion order. The replay depends on this order.
async def test_transactions_are_ordered_by_date_then_id(service, session, owner, portfolio):
    later = await add_tx(session, portfolio, "A", "SELL", 5, 50.0, "2026-01-07")
    first_same_day = await add_tx(session, portfolio, "A", "BUY", 10, 40.0, "2026-01-05")
    second_same_day = await add_tx(session, portfolio, "B", "BUY", 3, 20.0, "2026-01-05")

    result = await service.get_portfolio_transactions(portfolio.id, owner.id)

    assert [t.id for t in result] == [first_same_day.id, second_same_day.id, later.id]


# Only this portfolio's transactions, not the ones from the user's other
# portfolios.
async def test_transactions_of_other_portfolios_are_excluded(service, session, owner, portfolio):
    other = models.Portfolio(name="Other", user_id=owner.id)
    session.add(other)
    await session.commit()
    mine = await add_tx(session, portfolio, "A", "BUY", 10, 40.0, "2026-01-05")
    await add_tx(session, other, "B", "BUY", 3, 20.0, "2026-01-05")

    result = await service.get_portfolio_transactions(portfolio.id, owner.id)

    assert [t.id for t in result] == [mine.id]


async def test_transactions_of_empty_portfolio(service, owner, portfolio):
    assert await service.get_portfolio_transactions(portfolio.id, owner.id) == []


# Another user's portfolio and a portfolio that doesn't exist get the same
# 404, so the response doesn't reveal which portfolio ids exist.
async def test_transactions_of_another_users_portfolio_is_404(service, stranger, portfolio):
    with pytest.raises(HTTPException) as error:
        await service.get_portfolio_transactions(portfolio.id, stranger.id)

    assert error.value.status_code == 404
    assert error.value.detail == "Portfolio not found"


async def test_transactions_of_missing_portfolio_is_404(service, owner, portfolio):
    with pytest.raises(HTTPException) as error:
        await service.get_portfolio_transactions(portfolio.id + 1, owner.id)

    assert error.value.status_code == 404


# ---------------------------------------------------------------------------
# build_holdings_dictionary
# ---------------------------------------------------------------------------

async def test_holdings_average_cost_of_two_buys(service):
    result = service.build_holdings_dictionary([
        tx(1, "A", "BUY", 10, 40.0, "2026-01-05"),
        tx(2, "A", "BUY", 10, 60.0, "2026-01-06"),
    ])

    # 10*40 + 10*60 = 1000 for 20 shares, so 50 per share.
    assert result == {"A": holding("A", 20, 1000.0)}
    assert result["A"]["avg_cost_per_share"] == pytest.approx(50.0)


# A sell removes shares at the average cost; the sale price doesn't change
# the average cost of the shares left.
async def test_holdings_partial_sell_keeps_average_cost(service):
    result = service.build_holdings_dictionary([
        tx(1, "A", "BUY", 10, 40.0, "2026-01-05"),
        tx(2, "A", "BUY", 10, 60.0, "2026-01-06"),
        tx(3, "A", "SELL", 5, 90.0, "2026-01-07"),
    ])

    # 15 shares left at 50 each = 750.
    assert result["A"]["number_current_shares"] == 15
    assert result["A"]["avg_cost_per_share"] == pytest.approx(50.0)
    assert result["A"]["cost_bases"] == pytest.approx(750.0)


# A fully sold symbol stays in the dictionary with 0 shares and 0 cost;
# summarize_holdings filters it out.
async def test_holdings_fully_sold_symbol_has_zero_shares(service):
    result = service.build_holdings_dictionary([
        tx(1, "A", "BUY", 10, 40.0, "2026-01-05"),
        tx(2, "A", "SELL", 10, 45.0, "2026-01-06"),
    ])

    assert result == {"A": holding("A", 0, 0.0)}


# Buying again after selling everything starts a new average from scratch.
async def test_holdings_rebuy_after_full_sell_starts_new_average(service):
    result = service.build_holdings_dictionary([
        tx(1, "A", "BUY", 10, 40.0, "2026-01-05"),
        tx(2, "A", "SELL", 10, 45.0, "2026-01-06"),
        tx(3, "A", "BUY", 4, 70.0, "2026-01-07"),
    ])

    assert result == {"A": holding("A", 4, 280.0)}


async def test_holdings_symbols_are_independent(service):
    result = service.build_holdings_dictionary([
        tx(1, "A", "BUY", 10, 40.0, "2026-01-05"),
        tx(2, "B", "BUY", 5, 20.0, "2026-01-05"),
        tx(3, "A", "SELL", 4, 45.0, "2026-01-06"),
    ])

    assert result == {
        "A": holding("A", 6, 240.0),  # 6 shares * 40
        "B": holding("B", 5, 100.0),
    }


async def test_holdings_of_no_transactions(service):
    assert service.build_holdings_dictionary([]) == {}


# The ValueError from apply_transaction becomes a 400 with the same message.
async def test_holdings_oversell_is_400(service):
    with pytest.raises(HTTPException) as error:
        service.build_holdings_dictionary([
            tx(1, "A", "BUY", 5, 40.0, "2026-01-05"),
            tx(2, "A", "SELL", 6, 45.0, "2026-01-06"),
        ])

    assert error.value.status_code == 400
    assert error.value.detail == "Not enough shares to sell for A"


# ---------------------------------------------------------------------------
# enrich_holdings_with_current_prices
# ---------------------------------------------------------------------------

async def test_enrich_gain(service, current_price):
    current_price.return_value = 50.0

    result = await service.enrich_holdings_with_current_prices({"A": holding("A", 10, 400.0)})

    # 10 shares * 50 = 500; 500 - 400 = 100 gain; 100 / 400 = 25%.
    assert result["A"]["current_price_per_share"] == pytest.approx(50.0)
    assert result["A"]["current_value"] == pytest.approx(500.0)
    assert result["A"]["unrealized_gain_loss"] == pytest.approx(100.0)
    assert result["A"]["return_percentage"] == pytest.approx(25.0)


async def test_enrich_loss(service, current_price):
    current_price.return_value = 30.0

    result = await service.enrich_holdings_with_current_prices({"A": holding("A", 10, 400.0)})

    # 10 * 30 = 300; 300 - 400 = -100; -100 / 400 = -25%.
    assert result["A"]["unrealized_gain_loss"] == pytest.approx(-100.0)
    assert result["A"]["return_percentage"] == pytest.approx(-25.0)


# A failed lookup sets that symbol's price fields to None and the other
# symbols are still priced.
async def test_enrich_price_failure_sets_none(service, current_price):
    current_price.side_effect = prices({"B": 25.0})

    result = await service.enrich_holdings_with_current_prices({
        "A": holding("A", 10, 400.0),
        "B": holding("B", 4, 80.0),
    })

    assert result["A"] == {
        **holding("A", 10, 400.0),
        "current_price_per_share": None,
        "current_value": None,
        "unrealized_gain_loss": None,
        "return_percentage": None,
    }
    assert result["B"]["current_value"] == pytest.approx(100.0)  # 4 * 25


# Symbols with 0 shares are left as they are, without a price lookup.
async def test_enrich_skips_zero_share_symbols(service, current_price):
    current_price.return_value = 50.0

    result = await service.enrich_holdings_with_current_prices({
        "A": holding("A", 0, 0.0),
        "B": holding("B", 2, 80.0),
    })

    assert result["A"] == holding("A", 0, 0.0)
    current_price.assert_called_once_with("B")


# The guard against dividing by a zero cost basis (shares bought at 0).
async def test_enrich_zero_cost_basis_returns_zero_percent(service, current_price):
    current_price.return_value = 50.0

    result = await service.enrich_holdings_with_current_prices({"A": holding("A", 2, 0.0)})

    assert result["A"]["unrealized_gain_loss"] == pytest.approx(100.0)
    assert result["A"]["return_percentage"] == 0


# The dict is modified in place and the same object is returned.
async def test_enrich_modifies_dict_in_place(service, current_price):
    current_price.return_value = 50.0
    holdings = {"A": holding("A", 10, 400.0)}

    result = await service.enrich_holdings_with_current_prices(holdings)

    assert result is holdings
    assert holdings["A"]["current_value"] == pytest.approx(500.0)


# ---------------------------------------------------------------------------
# summarize_holdings
# ---------------------------------------------------------------------------

# End to end through the database: fully sold symbols are left out and the
# rest come back as HoldingBase.
async def test_summary_of_open_positions(service, session, owner, portfolio, current_price):
    await add_tx(session, portfolio, "A", "BUY", 10, 40.0, "2026-01-05")
    await add_tx(session, portfolio, "A", "SELL", 4, 45.0, "2026-01-06")
    await add_tx(session, portfolio, "B", "BUY", 5, 20.0, "2026-01-05")
    await add_tx(session, portfolio, "B", "SELL", 5, 25.0, "2026-01-07")
    current_price.side_effect = prices({"A": 50.0})

    result = await service.summarize_holdings(portfolio.id, owner.id)

    # A: 6 shares at 40 = 240 cost; 6 * 50 = 300 value; 60 gain; 25%.
    assert result == [
        HoldingBase(
            symbol="A",
            number_current_shares=6,
            avg_cost_per_share=40.0,
            cost_bases=240.0,
            current_price_per_share=50.0,
            current_value=300.0,
            unrealized_gain_loss=60.0,
            return_percentage=25.0,
        )
    ]
    current_price.assert_called_once_with("A")


# A failed price lookup doesn't fail the request: the holding is returned
# with its price fields set to None.
async def test_summary_price_failure_returns_none_fields(service, session, owner, portfolio, current_price):
    await add_tx(session, portfolio, "A", "BUY", 10, 40.0, "2026-01-05")
    current_price.side_effect = prices({})

    [result] = await service.summarize_holdings(portfolio.id, owner.id)

    assert result.cost_bases == pytest.approx(400.0)
    assert result.current_price_per_share is None
    assert result.current_value is None
    assert result.unrealized_gain_loss is None
    assert result.return_percentage is None


async def test_summary_of_empty_portfolio(service, owner, portfolio, current_price):
    assert await service.summarize_holdings(portfolio.id, owner.id) == []
    current_price.assert_not_called()


async def test_summary_of_another_users_portfolio_is_404(service, stranger, portfolio):
    with pytest.raises(HTTPException) as error:
        await service.summarize_holdings(portfolio.id, stranger.id)

    assert error.value.status_code == 404