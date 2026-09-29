"""Tests for services/auth_service.py (log-in and current user).

Like test_user_service.py, these use a real database: a fresh in-memory
SQLite per test, because the logic being tested is the queries (the
case-insensitive email lookup and the lookup by id). The password hashing
and JWT functions from security.py are the real ones too, so a token from
log-in is the same kind of token the API hands out.

Every failure must be a 401 with a WWW-Authenticate: Bearer header;
`assert_unauthorized` checks both, plus the detail message.
"""

from datetime import UTC, datetime, timedelta

import jwt
import pytest
from fastapi import HTTPException
from fastapi.security import OAuth2PasswordRequestForm
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from core.config import settings
from models import models
from security import create_access_token, hash_password
from services.auth_service import AuthService


# ---------------------------------------------------------------------------
# Fixtures and helpers
# ---------------------------------------------------------------------------

PASSWORD = "fakepassword"


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
    return AuthService(session)


@pytest.fixture
async def user(session):
    """A registered user. The email is stored lowercased, like
    UserService.create_user does."""
    user = models.User(
        username="Geralt",
        email="geralt@example.com",
        hashed_password=hash_password(PASSWORD),
    )
    session.add(user)
    await session.commit()
    return user


def login_form(username, password=PASSWORD):
    """The OAuth2 log-in form. Its `username` field holds the email."""
    return OAuth2PasswordRequestForm(username=username, password=password)


def decode(token):
    return jwt.decode(
        token,
        settings.secret_key.get_secret_value(),
        algorithms=[settings.algorithm],
    )


def assert_unauthorized(error, detail):
    assert error.value.status_code == 401
    assert error.value.detail == detail
    assert error.value.headers == {"WWW-Authenticate": "Bearer"}


# ---------------------------------------------------------------------------
# login_to_create_access_token
# ---------------------------------------------------------------------------

# The token's "sub" is the user id (as a string) and it expires after
# access_token_expire_minutes.
async def test_login_returns_bearer_token_for_user(service, user):
    before = datetime.now(UTC)

    token = await service.login_to_create_access_token(login_form("geralt@example.com"))

    assert token.token_type == "bearer"
    payload = decode(token.access_token)
    assert payload["sub"] == str(user.id)
    expected_exp = before + timedelta(minutes=settings.access_token_expire_minutes)
    assert payload["exp"] == pytest.approx(expected_exp.timestamp(), abs=5)


# The email is matched case-insensitively.
async def test_login_email_is_case_insensitive(service, user):
    token = await service.login_to_create_access_token(login_form("GERALT@Example.com"))

    assert decode(token.access_token)["sub"] == str(user.id)


# Wrong password, unknown email, and a username in place of the email all get
# the same message, so the response doesn't reveal which accounts exist.
@pytest.mark.parametrize(
    "form",
    [
        login_form("geralt@example.com", password="wrongpassword"),
        login_form("yennefer@example.com"),
        login_form("Geralt"),
    ],
    ids=["wrong-password", "unknown-email", "username-instead-of-email"],
)
async def test_login_with_bad_credentials_is_rejected(service, user, form):
    with pytest.raises(HTTPException) as error:
        await service.login_to_create_access_token(form)

    assert_unauthorized(error, "Incorrect email or password")


# ---------------------------------------------------------------------------
# get_current_user
# ---------------------------------------------------------------------------

# Round trip: the token that log-in returns resolves back to the same user.
async def test_login_token_resolves_to_user(service, user):
    token = await service.login_to_create_access_token(login_form("geralt@example.com"))

    current = await service.get_current_user(token.access_token)

    assert current.id == user.id
    assert current.email == "geralt@example.com"


# Tokens that verify_access_token rejects: not a JWT, expired, signed with
# another key, or missing one of the required "sub" and "exp" claims.
@pytest.mark.parametrize(
    "token",
    [
        "not-a-token",
        create_access_token({"sub": "1"}, expires_delta=timedelta(minutes=-1)),
        jwt.encode(
            {"sub": "1", "exp": datetime.now(UTC) + timedelta(minutes=5)},
            "another-secret-key-at-least-32-bytes-long", algorithm="HS256",
        ),
        create_access_token({}, expires_delta=timedelta(minutes=5)),
        jwt.encode({"sub": "1"}, settings.secret_key.get_secret_value(), algorithm=settings.algorithm),
    ],
    ids=["garbage", "expired", "wrong-key", "no-sub", "no-exp"],
)
async def test_invalid_token_is_rejected(service, user, token):
    with pytest.raises(HTTPException) as error:
        await service.get_current_user(token)

    assert_unauthorized(error, "Invalid or expired token")


# A correctly signed token whose "sub" isn't an integer id.
async def test_token_with_non_integer_sub_is_rejected(service, user):
    token = create_access_token({"sub": "geralt"}, expires_delta=timedelta(minutes=5))

    with pytest.raises(HTTPException) as error:
        await service.get_current_user(token)

    assert_unauthorized(error, "Invalid or expired token")


# A valid token for a user that doesn't exist (for example, one deleted after
# the token was issued).
async def test_token_for_missing_user_is_rejected(service, user):
    token = create_access_token({"sub": str(user.id + 1)}, expires_delta=timedelta(minutes=5))

    with pytest.raises(HTTPException) as error:
        await service.get_current_user(token)

    assert_unauthorized(error, "User not found")
