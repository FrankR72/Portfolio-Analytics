"""Tests for services/portfolio_service.py (create, list, rename, delete).

Every method is a query (ownership checks, the case-insensitive name
lookups, the cascade on delete), so all of these use a real database: a
fresh in-memory SQLite per test, like test_user_service.py. There is no
market data here, so nothing needs mocking.

The duplicate-name test on create expects 406, the current status code. It
is a known issue (it should be 409, like rename), so update the test when
that is fixed.
"""

from datetime import UTC, datetime

import pytest
from fastapi import HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from db.schemas import PortfolioCreate
from models import models
from services.portfolio_service import PortfolioService


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
    return PortfolioService(session)


@pytest.fixture
async def owner(session):
    user = models.User(username="Geralt", email="geralt@example.com", hashed_password="x")
    session.add(user)
    await session.commit()
    return user


@pytest.fixture
async def stranger(session):
    """A second user, to check that names and portfolios are per user."""
    user = models.User(username="Yennefer", email="yennefer@example.com", hashed_password="x")
    session.add(user)
    await session.commit()
    return user


async def add_portfolio(session, user, name):
    """Insert a portfolio directly, skipping the service's checks."""
    portfolio = models.Portfolio(name=name, user_id=user.id)
    session.add(portfolio)
    await session.commit()
    return portfolio


async def add_tx(session, portfolio, symbol="AAPL"):
    transaction = models.Transaction(
        symbol=symbol,
        transaction_type=models.TransactionType.BUY,
        quantity_actions=10,
        price=40.0,
        total_value=400.0,
        transaction_date=datetime(2026, 1, 5, tzinfo=UTC),
        portfolio_id=portfolio.id,
    )
    session.add(transaction)
    await session.commit()
    return transaction


async def stored_names(session, user):
    """Names of the user's portfolios that are in the database, by id."""
    result = await session.execute(
        select(models.Portfolio.name)
        .where(models.Portfolio.user_id == user.id)
        .order_by(models.Portfolio.id)
    )
    return list(result.scalars().all())


async def stored_transaction_portfolios(session):
    """portfolio_id of every transaction left in the database."""
    result = await session.execute(select(models.Transaction.portfolio_id))
    return sorted(result.scalars().all())


def not_owned(owner, stranger, portfolio, case):
    """(portfolio_id, user_id) for another user's portfolio or a missing one."""
    return {
        "another-user": (portfolio.id, stranger.id),
        "missing": (portfolio.id + 1, owner.id),
    }[case]


NOT_OWNED = ["another-user", "missing"]


def assert_not_found(error):
    assert error.value.status_code == 404
    assert error.value.detail == "Portfolio not found"


# ---------------------------------------------------------------------------
# create_portfolio
# ---------------------------------------------------------------------------

# The name is stored as typed (case included).
async def test_create_portfolio(service, session, owner):
    result = await service.create_portfolio(PortfolioCreate(name="Long Term"), owner.id)

    assert result.id is not None
    assert result.name == "Long Term"
    assert result.user_id == owner.id
    assert await stored_names(session, owner) == ["Long Term"]


# Names are compared case-insensitively, and nothing new is stored.
@pytest.mark.parametrize("name", ["Long Term", "LONG TERM", "long term"])
async def test_create_duplicate_name_is_406(service, session, owner, name):
    await add_portfolio(session, owner, "Long Term")

    with pytest.raises(HTTPException) as error:
        await service.create_portfolio(PortfolioCreate(name=name), owner.id)

    assert error.value.status_code == 406
    assert error.value.detail == "Portfolio name already exists"
    assert await stored_names(session, owner) == ["Long Term"]


# Names are unique per user: another user can use the same name.
async def test_create_name_used_by_another_user(service, session, owner, stranger):
    await add_portfolio(session, stranger, "Long Term")

    await service.create_portfolio(PortfolioCreate(name="Long Term"), owner.id)

    assert await stored_names(session, owner) == ["Long Term"]


# ---------------------------------------------------------------------------
# list_portfolios
# ---------------------------------------------------------------------------

# Only the user's own portfolios, ordered by id (creation order), not by name.
async def test_list_own_portfolios_by_id(service, session, owner, stranger):
    second = await add_portfolio(session, owner, "Zeta")
    await add_portfolio(session, stranger, "Theirs")
    third = await add_portfolio(session, owner, "Alpha")

    result = await service.list_portfolios(owner.id)

    assert [p.id for p in result] == [second.id, third.id]


async def test_list_without_portfolios(service, owner):
    assert await service.list_portfolios(owner.id) == []


# ---------------------------------------------------------------------------
# visualize_portfolio
# ---------------------------------------------------------------------------

async def test_visualize_portfolio(service, session, owner):
    portfolio = await add_portfolio(session, owner, "Main")

    result = await service.visualize_portfolio(portfolio.id, owner.id)

    assert result.id == portfolio.id
    assert result.name == "Main"


# Another user's portfolio and a missing one get the same 404, so the
# response doesn't reveal which portfolio ids exist.
@pytest.mark.parametrize("case", NOT_OWNED)
async def test_visualize_not_owned_is_404(service, session, owner, stranger, case):
    portfolio = await add_portfolio(session, owner, "Main")
    portfolio_id, user_id = not_owned(owner, stranger, portfolio, case)

    with pytest.raises(HTTPException) as error:
        await service.visualize_portfolio(portfolio_id, user_id)

    assert_not_found(error)


# ---------------------------------------------------------------------------
# update_portfolio
# ---------------------------------------------------------------------------

async def test_rename_portfolio(service, session, owner):
    portfolio = await add_portfolio(session, owner, "Main")

    result = await service.update_portfolio(portfolio.id, owner.id, "Retirement")

    assert result.name == "Retirement"
    assert await stored_names(session, owner) == ["Retirement"]


# The portfolio itself doesn't count as a duplicate, so its name's case can
# be changed.
async def test_rename_changing_only_case(service, session, owner):
    portfolio = await add_portfolio(session, owner, "main")

    await service.update_portfolio(portfolio.id, owner.id, "MAIN")

    assert await stored_names(session, owner) == ["MAIN"]


# Another of the user's portfolios already has the name (case-insensitive).
async def test_rename_to_duplicate_name_is_409(service, session, owner):
    portfolio = await add_portfolio(session, owner, "Main")
    await add_portfolio(session, owner, "Retirement")

    with pytest.raises(HTTPException) as error:
        await service.update_portfolio(portfolio.id, owner.id, "retirement")

    assert error.value.status_code == 409
    assert error.value.detail == "You already have a portfolio with that name"
    assert await stored_names(session, owner) == ["Main", "Retirement"]


async def test_rename_to_name_used_by_another_user(service, session, owner, stranger):
    portfolio = await add_portfolio(session, owner, "Main")
    await add_portfolio(session, stranger, "Retirement")

    await service.update_portfolio(portfolio.id, owner.id, "Retirement")

    assert await stored_names(session, owner) == ["Retirement"]


@pytest.mark.parametrize("case", NOT_OWNED)
async def test_rename_not_owned_is_404(service, session, owner, stranger, case):
    portfolio = await add_portfolio(session, owner, "Main")
    portfolio_id, user_id = not_owned(owner, stranger, portfolio, case)

    with pytest.raises(HTTPException) as error:
        await service.update_portfolio(portfolio_id, user_id, "Hacked")

    assert_not_found(error)
    assert await stored_names(session, owner) == ["Main"]


# ---------------------------------------------------------------------------
# delete_portfolio
# ---------------------------------------------------------------------------

# Deleting a portfolio also deletes its transactions (ORM cascade), and
# leaves the user's other portfolios and their transactions alone.
async def test_delete_portfolio_cascades_transactions(service, session, owner):
    doomed = await add_portfolio(session, owner, "Main")
    kept = await add_portfolio(session, owner, "Retirement")
    await add_tx(session, doomed, "AAPL")
    await add_tx(session, doomed, "MSFT")
    await add_tx(session, kept, "AAPL")

    await service.delete_portfolio(doomed.id, owner.id)

    assert await stored_names(session, owner) == ["Retirement"]
    assert await stored_transaction_portfolios(session) == [kept.id]


@pytest.mark.parametrize("case", NOT_OWNED)
async def test_delete_not_owned_is_404(service, session, owner, stranger, case):
    portfolio = await add_portfolio(session, owner, "Main")
    await add_tx(session, portfolio)
    portfolio_id, user_id = not_owned(owner, stranger, portfolio, case)

    with pytest.raises(HTTPException) as error:
        await service.delete_portfolio(portfolio_id, user_id)

    assert_not_found(error)
    assert await stored_names(session, owner) == ["Main"]
    assert await stored_transaction_portfolios(session) == [portfolio.id]