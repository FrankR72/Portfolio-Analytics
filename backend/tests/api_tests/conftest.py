"""Shared fixtures for the API tests.

The API tests send real HTTP requests to the FastAPI app, so they cover
what the service tests skip: routing, status codes set by the routers,
dependencies such as get_current_user, and response_model filtering.

How it works:
    - httpx.AsyncClient with ASGITransport calls the app in memory. No
      server is started and no port is opened.
    - get_db is overridden to yield a session on a fresh in-memory SQLite
      database, so backend/test.db is never touched. Every request in a test
      shares that one session, and the `session` fixture gives the test the
      same session to check rows directly.
    - ASGITransport doesn't run the app's lifespan, so the startup
      create_all on test.db never runs; the `session` fixture creates the
      tables itself.
    - yfinance is blocked in every test (block_yfinance). Tests that need
      prices patch them explicitly.
    - An exception the app doesn't handle is re-raised in the test instead
      of becoming a 500 response, so a bug shows its full traceback.

Unlike the service tests, these fixtures are shared by every file in this
folder, because every API test needs the same client and users.
"""

from datetime import UTC, datetime
from types import SimpleNamespace

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from db.database import get_db
from main import app
from models import models


# ---------------------------------------------------------------------------
# No network
# ---------------------------------------------------------------------------

@pytest.fixture(autouse=True)
def block_yfinance(mocker):
    """Make every real yfinance call fail, in every API test.

    market_data_service turns the error into a ValueError, as if Yahoo
    Finance were unreachable. Tests that need prices patch the price
    functions where the services import them, for example
    services.holding_service.get_current_stock_price.
    """
    fake_yf = mocker.patch("services.market_data_service.yf")
    fake_yf.Ticker.side_effect = RuntimeError("yfinance must not be called in tests")


# ---------------------------------------------------------------------------
# Database and client
# ---------------------------------------------------------------------------

@pytest.fixture
async def session():
    """Session on a new, empty in-memory database with all tables created.

    The engine is disposed after the test, which deletes the database.
    """
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as conn:
        await conn.run_sync(models.Base.metadata.create_all)
    async with async_sessionmaker(engine, expire_on_commit=False)() as s:
        yield s
    await engine.dispose()


@pytest.fixture
async def client(session):
    """HTTP client for the app, with get_db replaced by the test session."""

    async def override_get_db():
        yield session

    app.dependency_overrides[get_db] = override_get_db
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
        yield ac
    # Always undo the override, so it can't leak into another test.
    app.dependency_overrides.clear()


# ---------------------------------------------------------------------------
# Users and tokens
# ---------------------------------------------------------------------------

# These fixtures return functions ("factory fixtures"), so one test can
# create several users with different data.

@pytest.fixture
def create_user(client):
    """Return an async function that signs up a user through POST /api/users."""

    async def _create_user(
        username: str = "Geralt",
        email: str = "geralt@example.com",
        password: str = "fakepassword",
    ) -> dict:
        response = await client.post(
            "/api/users",
            json={"username": username, "email": email, "password": password},
        )
        assert response.status_code == 201, response.text
        return response.json()

    return _create_user


@pytest.fixture
def login(client):
    """Return an async function that logs in through POST /api/auth/token
    and returns the headers to send with authenticated requests."""

    async def _login(
        email: str = "geralt@example.com",
        password: str = "fakepassword",
    ) -> dict[str, str]:
        # OAuth2 form, not JSON: the `username` field holds the email.
        response = await client.post(
            "/api/auth/token",
            data={"username": email, "password": password},
        )
        assert response.status_code == 200, response.text
        return {"Authorization": f"Bearer {response.json()['access_token']}"}

    return _login


@pytest.fixture
async def owner(create_user, login):
    """Signed-up and logged-in user who owns the test data.

    `owner.id` is the user id and `owner.headers` the Authorization header.
    """
    user = await create_user(username="Geralt", email="geralt@example.com")
    headers = await login(email="geralt@example.com")
    return SimpleNamespace(id=user["id"], headers=headers)


@pytest.fixture
async def stranger(create_user, login):
    """A second logged-in user, who must not see the owner's data."""
    user = await create_user(username="Ciri", email="ciri@example.com")
    headers = await login(email="ciri@example.com")
    return SimpleNamespace(id=user["id"], headers=headers)


# ---------------------------------------------------------------------------
# Portfolios and transactions
# ---------------------------------------------------------------------------

@pytest.fixture
async def portfolio(client, owner) -> dict:
    """The owner's portfolio "Main", created through POST /api/portfolios."""
    response = await client.post("/api/portfolios", json={"name": "Main"}, headers=owner.headers)
    assert response.status_code == 201, response.text
    return response.json()


@pytest.fixture
def add_tx(session):
    """Return an async function that inserts a transaction directly.

    It skips the API and the service's checks (ticker lookup, oversell), so
    a test can set up any history, including invalid ones. The date is
    midnight UTC, like register_transaction stores it, and ids follow the
    insertion order.
    """

    async def _add_tx(portfolio: dict, symbol: str, side: str, qty: int, price: float, day: str) -> int:
        transaction = models.Transaction(
            symbol=symbol,
            transaction_type=models.TransactionType(side),
            quantity_actions=qty,
            price=price,
            total_value=qty * price,
            transaction_date=datetime.fromisoformat(day).replace(tzinfo=UTC),
            portfolio_id=portfolio["id"],
        )
        session.add(transaction)
        await session.commit()
        return transaction.id

    return _add_tx


@pytest.fixture
def count_transactions(session):
    """Return an async function giving the number of transactions stored
    for a portfolio. Used to check that a rejected request inserted or
    deleted nothing."""

    async def _count_transactions(portfolio: dict) -> int:
        return await session.scalar(
            select(func.count())
            .select_from(models.Transaction)
            .where(models.Transaction.portfolio_id == portfolio["id"])
        )

    return _count_transactions
