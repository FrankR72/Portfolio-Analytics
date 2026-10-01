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

Unlike the service tests, these fixtures are shared by every file in this
folder, because every API test needs the same client and users.
"""

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from db.database import get_db
from main import app
from models import models


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
