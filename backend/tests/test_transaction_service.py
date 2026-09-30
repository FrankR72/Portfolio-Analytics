"""Tests for services/transaction_service.py (BUY/SELL transactions).

Two kinds of tests, depending on what each method does:

- register_transaction, get_transactions, get_closed_transactions and
  delete_transaction run queries (ownership checks, ordering, the share
  count replayed from the stored history), so they use a real database: a
  fresh in-memory SQLite per test, like test_holding_service.py.
- build_closed_transactions is pure logic, so it gets plain fake
  transactions built with `tx()` and never touches the database.

The ticker check is always mocked, so nothing calls yfinance. Expected
numbers are calculated by hand and written in comments next to the test.

register_transaction returns the stored model; creating a transaction
answering 200 instead of 201 is decided in the router, not tested here.
"""

from datetime import UTC, date, datetime
from types import SimpleNamespace

import pytest
from fastapi import HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from db.schemas import ClosedTransaction, TransactionCreate
from models import models
from services.transaction_service import TransactionService


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
    return TransactionService(session)


@pytest.fixture
async def owner(session):
    user = models.User(username="Geralt", email="geralt@example.com", hashed_password="x")
    session.add(user)
    await session.commit()
    return user


@pytest.fixture
async def stranger(session):
    """A second user, to check that one user can't use another's portfolio."""
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


@pytest.fixture
async def other_portfolio(session, owner):
    """A second portfolio of the same user."""
    portfolio = models.Portfolio(name="Other", user_id=owner.id)
    session.add(portfolio)
    await session.commit()
    return portfolio


async def add_tx(session, portfolio, symbol, side, qty, price, day):
    """Insert a transaction directly, skipping the service's checks. Ids
    follow the insertion order, and the date is midnight UTC like
    register_transaction stores it."""
    transaction = models.Transaction(
        symbol=symbol,
        transaction_type=models.TransactionType(side),
        quantity_actions=qty,
        price=price,
        total_value=qty * price,
        transaction_date=datetime.fromisoformat(day).replace(tzinfo=UTC),
        portfolio_id=portfolio.id,
    )
    session.add(transaction)
    await session.commit()
    return transaction


async def stored_ids(session, portfolio):
    """Ids of the transactions that are in the database for a portfolio."""
    result = await session.execute(
        select(models.Transaction.id)
        .where(models.Transaction.portfolio_id == portfolio.id)
        .order_by(models.Transaction.id)
    )
    return list(result.scalars().all())


def new(symbol, side, qty, price, day=None):
    """The request body of POST /api/transactions."""
    return TransactionCreate(
        symbol=symbol,
        transaction_type=side,
        quantity_actions=qty,
        price=price,
        transaction_date=date.fromisoformat(day) if day else None,
    )


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


def assert_sale(sale, symbol, shares, avg_cost, price, gain, percentage):
    """Check one ClosedTransaction. The totals follow from the other fields."""
    assert isinstance(sale, ClosedTransaction)
    assert sale.symbol == symbol
    assert sale.number_shares_sold == shares
    assert sale.avg_cost_per_share == pytest.approx(avg_cost)
    assert sale.sold_price_per_share == pytest.approx(price)
    assert sale.total_cost_of_shares_sold == pytest.approx(avg_cost * shares)
    assert sale.total_sold_price == pytest.approx(price * shares)
    assert sale.realized_gain_loss == pytest.approx(gain)
    assert sale.return_percentage == pytest.approx(percentage)


# Patched in transaction_service, not in market_data_service, because
# transaction_service imported it by name.
@pytest.fixture
def ticker_ok(mocker):
    """Fake ticker check. Accepts every ticker unless return_value is set
    to False."""
    return mocker.patch("services.transaction_service.ticker_validation", return_value=True)


def assert_bad_sell(error):
    assert error.value.status_code == 400
    assert error.value.detail == "Not enough shares to sell on that date"


# ---------------------------------------------------------------------------
# register_transaction
# ---------------------------------------------------------------------------

# The symbol is stripped and uppercased, total_value is quantity * price, and
# the date is stored as midnight UTC of that day.
async def test_register_buy_is_stored(service, session, owner, portfolio, ticker_ok):
    result = await service.register_transaction(
        new(" aapl ", "BUY", 10, 40.5, "2026-01-05"), portfolio.id, owner.id
    )

    assert result.id is not None
    assert result.portfolio_id == portfolio.id
    assert result.symbol == "AAPL"
    assert result.transaction_type == models.TransactionType.BUY
    assert result.quantity_actions == 10
    assert result.total_value == pytest.approx(405.0)  # 10 * 40.5
    # SQLite gives the date back without a timezone.
    assert result.transaction_date.replace(tzinfo=None) == datetime(2026, 1, 5)
    assert await stored_ids(session, portfolio) == [result.id]
    ticker_ok.assert_called_once_with("AAPL")


# Without a date, the current time is used.
async def test_register_without_date_uses_now(service, owner, portfolio, ticker_ok):
    before = datetime.now(UTC)

    result = await service.register_transaction(new("AAPL", "BUY", 1, 10.0), portfolio.id, owner.id)

    stored = result.transaction_date.replace(tzinfo=UTC)
    assert before <= stored <= datetime.now(UTC)


async def test_register_unknown_ticker_is_422(service, session, owner, portfolio, ticker_ok):
    ticker_ok.return_value = False

    with pytest.raises(HTTPException) as error:
        await service.register_transaction(new("NOPE", "BUY", 1, 10.0), portfolio.id, owner.id)

    assert error.value.status_code == 422
    assert await stored_ids(session, portfolio) == []


# The ownership check runs first, so another user's portfolio id doesn't
# even reach yfinance. A missing portfolio gets the same 404.
@pytest.mark.parametrize("whose", ["another-user", "missing"])
async def test_register_in_portfolio_not_owned_is_404(service, owner, stranger, portfolio, ticker_ok, whose):
    user_id, portfolio_id = (
        (stranger.id, portfolio.id) if whose == "another-user" else (owner.id, portfolio.id + 1)
    )

    with pytest.raises(HTTPException) as error:
        await service.register_transaction(new("AAPL", "BUY", 1, 10.0), portfolio_id, user_id)

    assert error.value.status_code == 404
    assert error.value.detail == "Portfolio not found"
    ticker_ok.assert_not_called()


async def test_register_sell_within_holdings(service, session, owner, portfolio, ticker_ok):
    await add_tx(session, portfolio, "AAPL", "BUY", 10, 40.0, "2026-01-05")

    result = await service.register_transaction(
        new("AAPL", "SELL", 10, 50.0, "2026-01-06"), portfolio.id, owner.id
    )

    assert result.transaction_type == models.TransactionType.SELL
    assert len(await stored_ids(session, portfolio)) == 2


# A sale on the same day as the buy is placed after it (the new transaction
# has no id yet, so it goes after the existing ones with the same date).
async def test_register_sell_on_same_day_as_buy(service, session, owner, portfolio, ticker_ok):
    await add_tx(session, portfolio, "AAPL", "BUY", 10, 40.0, "2026-01-05")

    await service.register_transaction(new("AAPL", "SELL", 10, 50.0, "2026-01-05"), portfolio.id, owner.id)

    assert len(await stored_ids(session, portfolio)) == 2


async def test_register_oversell_is_400(service, session, owner, portfolio, ticker_ok):
    buy = await add_tx(session, portfolio, "AAPL", "BUY", 10, 40.0, "2026-01-05")

    with pytest.raises(HTTPException) as error:
        await service.register_transaction(new("AAPL", "SELL", 11, 50.0, "2026-01-06"), portfolio.id, owner.id)

    assert_bad_sell(error)
    assert await stored_ids(session, portfolio) == [buy.id]


# A backdated sell is checked against the shares held on its own date, not
# today: on 01-04 the shares from the 01-05 buy weren't held yet.
async def test_register_sell_before_the_buy_is_400(service, session, owner, portfolio, ticker_ok):
    await add_tx(session, portfolio, "AAPL", "BUY", 10, 40.0, "2026-01-05")

    with pytest.raises(HTTPException) as error:
        await service.register_transaction(new("AAPL", "SELL", 5, 50.0, "2026-01-04"), portfolio.id, owner.id)

    assert_bad_sell(error)


# A backdated sell that is covered on its date can still break a later sell
# that is already stored: 10 bought, 5 sold on 01-07 leaves 5, and the
# stored sell of 8 on 01-10 would take it to -3.
async def test_register_backdated_sell_breaking_later_sell_is_400(service, session, owner, portfolio, ticker_ok):
    await add_tx(session, portfolio, "AAPL", "BUY", 10, 40.0, "2026-01-05")
    await add_tx(session, portfolio, "AAPL", "SELL", 8, 45.0, "2026-01-10")

    with pytest.raises(HTTPException) as error:
        await service.register_transaction(new("AAPL", "SELL", 5, 50.0, "2026-01-07"), portfolio.id, owner.id)

    assert_bad_sell(error)


# Only shares of the same symbol in the same portfolio count.
@pytest.mark.parametrize("holding_in", ["other-symbol", "other-portfolio"])
async def test_register_sell_ignores_other_holdings(
    service, session, owner, portfolio, other_portfolio, ticker_ok, holding_in
):
    if holding_in == "other-symbol":
        await add_tx(session, portfolio, "MSFT", "BUY", 10, 40.0, "2026-01-05")
    else:
        await add_tx(session, other_portfolio, "AAPL", "BUY", 10, 40.0, "2026-01-05")

    with pytest.raises(HTTPException) as error:
        await service.register_transaction(new("AAPL", "SELL", 1, 50.0, "2026-01-06"), portfolio.id, owner.id)

    assert_bad_sell(error)


# ---------------------------------------------------------------------------
# get_transactions
# ---------------------------------------------------------------------------

# Ordered by id (insertion order), not by date: the backdated BUY inserted
# last comes last.
async def test_transactions_are_ordered_by_id(service, session, owner, portfolio):
    first = await add_tx(session, portfolio, "AAPL", "BUY", 10, 40.0, "2026-01-07")
    backdated = await add_tx(session, portfolio, "AAPL", "BUY", 5, 30.0, "2026-01-02")

    result = await service.get_transactions(portfolio.id, owner.id)

    assert [t.id for t in result] == [first.id, backdated.id]


async def test_transactions_of_other_portfolios_are_excluded(service, session, owner, portfolio, other_portfolio):
    mine = await add_tx(session, portfolio, "AAPL", "BUY", 10, 40.0, "2026-01-05")
    await add_tx(session, other_portfolio, "MSFT", "BUY", 3, 20.0, "2026-01-05")

    result = await service.get_transactions(portfolio.id, owner.id)

    assert [t.id for t in result] == [mine.id]


async def test_transactions_of_empty_portfolio(service, owner, portfolio):
    assert await service.get_transactions(portfolio.id, owner.id) == []


async def test_transactions_of_another_users_portfolio_is_404(service, stranger, portfolio):
    with pytest.raises(HTTPException) as error:
        await service.get_transactions(portfolio.id, stranger.id)

    assert error.value.status_code == 404
    assert error.value.detail == "Portfolio not found"


# ---------------------------------------------------------------------------
# build_closed_transactions
# ---------------------------------------------------------------------------

# One ClosedTransaction per SELL, none for BUYs. The sale is valued at the
# average cost of everything bought before it.
async def test_closed_one_per_sell_at_average_cost(service):
    result = service.build_closed_transactions([
        tx(1, "A", "BUY", 10, 40.0, "2026-01-05"),
        tx(2, "A", "BUY", 10, 60.0, "2026-01-06"),
        tx(3, "A", "SELL", 5, 70.0, "2026-01-07"),
    ])

    # Average cost (400 + 600) / 20 = 50. 5 * 70 = 350 - 250 = 100 gain;
    # 100 / 250 = 40%.
    [sale] = result
    assert_sale(sale, "A", 5, 50.0, 70.0, gain=100.0, percentage=40.0)
    assert sale.transaction_date == datetime(2026, 1, 7)


async def test_closed_loss(service):
    [sale] = service.build_closed_transactions([
        tx(1, "A", "BUY", 10, 40.0, "2026-01-05"),
        tx(2, "A", "SELL", 4, 30.0, "2026-01-06"),
    ])

    # 4 * 30 = 120 - 160 = -40; -40 / 160 = -25%.
    assert_sale(sale, "A", 4, 40.0, 30.0, gain=-40.0, percentage=-25.0)


# Two sells of the same position: the second one uses the average cost of
# the shares left, which the first sale didn't change.
async def test_closed_two_sells_keep_average_cost(service):
    first, second = service.build_closed_transactions([
        tx(1, "A", "BUY", 10, 40.0, "2026-01-05"),
        tx(2, "A", "SELL", 4, 50.0, "2026-01-06"),
        tx(3, "A", "SELL", 6, 35.0, "2026-01-07"),
    ])

    assert_sale(first, "A", 4, 40.0, 50.0, gain=40.0, percentage=25.0)
    assert_sale(second, "A", 6, 40.0, 35.0, gain=-30.0, percentage=-12.5)


# Buying again after selling everything starts a new average cost.
async def test_closed_rebuy_after_full_sell_starts_new_average(service):
    _, second = service.build_closed_transactions([
        tx(1, "A", "BUY", 10, 40.0, "2026-01-05"),
        tx(2, "A", "SELL", 10, 45.0, "2026-01-06"),
        tx(3, "A", "BUY", 5, 80.0, "2026-01-07"),
        tx(4, "A", "SELL", 5, 100.0, "2026-01-08"),
    ])

    # 5 * 100 = 500 - 400 = 100; 100 / 400 = 25%.
    assert_sale(second, "A", 5, 80.0, 100.0, gain=100.0, percentage=25.0)


# Each symbol has its own position, and the sales come back in replay order.
async def test_closed_symbols_are_independent(service):
    result = service.build_closed_transactions([
        tx(1, "A", "BUY", 10, 40.0, "2026-01-05"),
        tx(2, "B", "BUY", 5, 100.0, "2026-01-05"),
        tx(3, "B", "SELL", 5, 110.0, "2026-01-06"),
        tx(4, "A", "SELL", 10, 44.0, "2026-01-07"),
    ])

    assert [sale.symbol for sale in result] == ["B", "A"]
    assert_sale(result[0], "B", 5, 100.0, 110.0, gain=50.0, percentage=10.0)
    assert_sale(result[1], "A", 10, 40.0, 44.0, gain=40.0, percentage=10.0)


async def test_closed_only_buys(service):
    assert service.build_closed_transactions([tx(1, "A", "BUY", 10, 40.0, "2026-01-05")]) == []


async def test_closed_of_no_transactions(service):
    assert service.build_closed_transactions([]) == []


# The ValueError from apply_transaction becomes a 400 with the same message.
async def test_closed_oversell_is_400(service):
    with pytest.raises(HTTPException) as error:
        service.build_closed_transactions([
            tx(1, "A", "BUY", 5, 40.0, "2026-01-05"),
            tx(2, "A", "SELL", 6, 45.0, "2026-01-06"),
        ])

    assert error.value.status_code == 400
    assert error.value.detail == "Not enough shares to sell for A"


# ---------------------------------------------------------------------------
# get_closed_transactions
# ---------------------------------------------------------------------------

# Through the database the replay goes by date, not by id: the BUY inserted
# after the SELL but dated before it still covers it.
async def test_closed_from_database_replays_by_date(service, session, owner, portfolio):
    await add_tx(session, portfolio, "AAPL", "SELL", 5, 70.0, "2026-01-07")
    await add_tx(session, portfolio, "AAPL", "BUY", 10, 50.0, "2026-01-05")

    [sale] = await service.get_closed_transactions(portfolio.id, owner.id)

    # 5 * 70 = 350 - 250 = 100; 100 / 250 = 40%.
    assert_sale(sale, "AAPL", 5, 50.0, 70.0, gain=100.0, percentage=40.0)


async def test_closed_from_database_excludes_other_portfolios(service, session, owner, portfolio, other_portfolio):
    await add_tx(session, other_portfolio, "AAPL", "BUY", 10, 50.0, "2026-01-05")
    await add_tx(session, other_portfolio, "AAPL", "SELL", 5, 70.0, "2026-01-07")

    assert await service.get_closed_transactions(portfolio.id, owner.id) == []


# A stored history that doesn't add up (it can only get there by skipping
# the service's checks) is a 400.
async def test_closed_from_invalid_history_is_400(service, session, owner, portfolio):
    await add_tx(session, portfolio, "AAPL", "SELL", 5, 70.0, "2026-01-07")

    with pytest.raises(HTTPException) as error:
        await service.get_closed_transactions(portfolio.id, owner.id)

    assert error.value.status_code == 400


async def test_closed_of_another_users_portfolio_is_404(service, stranger, portfolio):
    with pytest.raises(HTTPException) as error:
        await service.get_closed_transactions(portfolio.id, stranger.id)

    assert error.value.status_code == 404
    assert error.value.detail == "Portfolio not found"


# ---------------------------------------------------------------------------
# delete_transaction
# ---------------------------------------------------------------------------

# A SELL can always be deleted: it only increases the shares held later.
async def test_delete_sell(service, session, owner, portfolio):
    buy = await add_tx(session, portfolio, "AAPL", "BUY", 10, 40.0, "2026-01-05")
    sell = await add_tx(session, portfolio, "AAPL", "SELL", 10, 50.0, "2026-01-06")

    await service.delete_transaction(sell.id, portfolio.id, owner.id)

    assert await stored_ids(session, portfolio) == [buy.id]


# A BUY that no SELL needs: the other BUY still covers the sale of 5.
async def test_delete_buy_not_needed(service, session, owner, portfolio):
    first = await add_tx(session, portfolio, "AAPL", "BUY", 10, 40.0, "2026-01-05")
    second = await add_tx(session, portfolio, "AAPL", "BUY", 3, 45.0, "2026-01-06")
    sell = await add_tx(session, portfolio, "AAPL", "SELL", 5, 50.0, "2026-01-07")

    await service.delete_transaction(second.id, portfolio.id, owner.id)

    assert await stored_ids(session, portfolio) == [first.id, sell.id]


# Only the deleted BUY's symbol is replayed, so a sale of another symbol
# doesn't block it.
async def test_delete_buy_of_other_symbol(service, session, owner, portfolio):
    await add_tx(session, portfolio, "AAPL", "BUY", 10, 40.0, "2026-01-05")
    msft = await add_tx(session, portfolio, "MSFT", "BUY", 3, 45.0, "2026-01-05")
    await add_tx(session, portfolio, "AAPL", "SELL", 10, 50.0, "2026-01-06")

    await service.delete_transaction(msft.id, portfolio.id, owner.id)

    assert msft.id not in await stored_ids(session, portfolio)


# Without the 01-06 BUY, only 10 shares cover the SELL of 12, so it's a 409
# and nothing is deleted.
async def test_delete_buy_needed_by_later_sell_is_409(service, session, owner, portfolio):
    await add_tx(session, portfolio, "AAPL", "BUY", 10, 40.0, "2026-01-05")
    needed = await add_tx(session, portfolio, "AAPL", "BUY", 5, 45.0, "2026-01-06")
    await add_tx(session, portfolio, "AAPL", "SELL", 12, 50.0, "2026-01-07")

    with pytest.raises(HTTPException) as error:
        await service.delete_transaction(needed.id, portfolio.id, owner.id)

    assert error.value.status_code == 409
    assert error.value.detail == "Deleting this BUY would leave a later SELL without enough shares"
    assert len(await stored_ids(session, portfolio)) == 3


# The transaction must exist, be in the given portfolio, and that portfolio
# must be the user's. All three failures are the same 404.
@pytest.mark.parametrize("case", ["missing-id", "wrong-portfolio", "another-user"])
async def test_delete_not_owned_is_404(service, session, owner, stranger, portfolio, other_portfolio, case):
    buy = await add_tx(session, portfolio, "AAPL", "BUY", 10, 40.0, "2026-01-05")
    transaction_id, portfolio_id, user_id = {
        "missing-id": (buy.id + 1, portfolio.id, owner.id),
        "wrong-portfolio": (buy.id, other_portfolio.id, owner.id),
        "another-user": (buy.id, portfolio.id, stranger.id),
    }[case]

    with pytest.raises(HTTPException) as error:
        await service.delete_transaction(transaction_id, portfolio_id, user_id)

    assert error.value.status_code == 404
    assert error.value.detail == "Transaction not found"
    assert await stored_ids(session, portfolio) == [buy.id]
