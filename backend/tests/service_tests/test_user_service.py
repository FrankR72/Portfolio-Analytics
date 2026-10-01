"""Tests for services/user_service.py (sign-up).

Unlike the other service tests, these use a real database: a fresh in-memory
SQLite per test. The logic being tested is the queries themselves
(case-insensitive username and email lookups), so mocking the session would
leave nothing to test.

The duplicate-username test expects 406, the current status code. It is a
known issue (it should be 409), so update the test when that is fixed.
"""

import pytest

from fastapi import HTTPException
from sqlalchemy import select, func
from sqlalchemy.ext.asyncio import create_async_engine, async_sessionmaker

from models import models
from db.schemas import UserCreate
from services.user_service import UserService


# ---------------------------------------------------------------------------
# Fixtures and helpers
# ---------------------------------------------------------------------------

@pytest.fixture
async def session():
    """Session on a new, empty in-memory database with all tables created.

    expire_on_commit=False keeps the returned user's attributes readable
    after the service commits. The engine is disposed after the test, which
    deletes the database.
    """
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as conn:
        await conn.run_sync(models.Base.metadata.create_all)
    async with async_sessionmaker(engine, expire_on_commit=False)() as s:
        yield s
    await engine.dispose()


@pytest.fixture
def service(session):
    return UserService(session)


def make_user(username: str = "Geralt", email: str = "GeraltofRivia@example.com", password: str = "fakepassword"):
    """Sign-up data. The default email is mixed case on purpose, to check
    that it is stored lowercased."""
    return UserCreate(username=username, email=email, password=password)


async def count_user(session):
    """Number of users in the database. Used to check that a rejected
    sign-up didn't insert anything."""
    return await session.scalar(select(func.count()).select_from(models.User))


# ---------------------------------------------------------------------------
# create_user
# ---------------------------------------------------------------------------

# The username keeps its case, the email is lowercased, and the password is
# stored hashed, never as plain text.
async def test_create_user(service, session):
    user = await service.create_user(make_user())

    assert user.id is not None
    assert user.username == "Geralt"
    assert user.email == "geraltofrivia@example.com"
    assert user.hashed_password != "fakepassword"
    assert await count_user(session) == 1


# Same username with a different email: rejected with 406 (see the module
# docstring), and the second user is not inserted.
async def test_duplicate_user_is_rejected(service, session):
    await service.create_user(make_user())

    with pytest.raises(HTTPException) as exc:
        await service.create_user(make_user(email="yukiomishima@gmail.com"))

    assert exc.value.status_code == 406
    assert await count_user(session) == 1


# Same email in a different case (all caps): the check is case-insensitive,
# so it is rejected with 400 and not inserted.
async def test_duplicate_email_is_rejected(service, session):
    await service.create_user(make_user())

    with pytest.raises(HTTPException) as exc:
        await service.create_user(make_user(username="Yukio", email="GERALTOFRIVIA@example.com"))

    assert exc.value.status_code == 400
    assert await count_user(session) == 1
