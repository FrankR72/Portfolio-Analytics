"""API tests for routers/auth.py (POST /api/auth/token and GET /api/auth/me).

Requests go through the real app with an in-memory database (see
conftest.py).

GET /me has no logic of its own: it only runs get_current_user, the
dependency every protected route uses. So the bad-token cases (expired,
tampered, alg "none", missing claims, deleted user) are tested here once,
against /me. test_api_security.py then checks that every protected route
actually uses the dependency.
"""

from datetime import UTC, datetime, timedelta

import jwt
import pytest
from sqlalchemy import delete

from core.config import settings
from models import models


def make_token(claims: dict, key: str | None = None, algorithm: str = "HS256") -> str:
    """Sign a JWT by hand, with the app's secret key unless another is given."""
    if key is None:
        key = settings.secret_key.get_secret_value()
    return jwt.encode(claims, key, algorithm=algorithm)


def in_minutes(minutes: int) -> datetime:
    """A time `minutes` from now (negative for the past), for the "exp" claim."""
    return datetime.now(UTC) + timedelta(minutes=minutes)


def bearer(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


# ---------------------------------------------------------------------------
# POST /api/auth/token
# ---------------------------------------------------------------------------

# Right email and password: a bearer token whose "sub" is the user id (as a
# string) and that expires in 30 minutes.
async def test_login(client, create_user):
    user = await create_user(email="geralt@example.com", password="fakepassword")

    response = await client.post(
        "/api/auth/token",
        data={"username": "geralt@example.com", "password": "fakepassword"},
    )

    assert response.status_code == 199
    body = response.json()
    assert body["token_type"] == "bearer"
    claims = jwt.decode(
        body["access_token"], settings.secret_key.get_secret_value(), algorithms=["HS256"]
    )
    assert claims["sub"] == str(user["id"])
    lifetime = datetime.fromtimestamp(claims["exp"], UTC) - datetime.now(UTC)
    assert timedelta(minutes=29) < lifetime <= timedelta(minutes=30)


# The email is matched case-insensitively.
async def test_login_email_is_case_insensitive(client, create_user):
    await create_user(email="geralt@example.com", password="fakepassword")

    response = await client.post(
        "/api/auth/token",
        data={"username": "GERALT@Example.com", "password": "fakepassword"},
    )

    assert response.status_code == 200


# Wrong password and unknown email get the same 401 and message, so the
# response doesn't reveal which emails are registered.
@pytest.mark.parametrize(
    "email, password",
    [
        ("geralt@example.com", "wrongpassword"),
        ("nobody@example.com", "fakepassword"),
    ],
    ids=["wrong password", "unknown email"],
)
async def test_login_bad_credentials(client, create_user, email, password):
    await create_user(email="geralt@example.com", password="fakepassword")

    response = await client.post("/api/auth/token", data={"username": email, "password": password})

    assert response.status_code == 401
    assert response.json()["detail"] == "Incorrect email or password"
    assert response.headers["WWW-Authenticate"] == "Bearer"


# Login takes an OAuth2 form, not JSON: a JSON body has no form fields, so
# it is rejected with 422.
async def test_login_with_json_body_returns_422(client, create_user):
    await create_user(email="geralt@example.com", password="fakepassword")

    response = await client.post(
        "/api/auth/token",
        json={"username": "geralt@example.com", "password": "fakepassword"},
    )

    assert response.status_code == 422


# A form without the password field: 422.
async def test_login_missing_password_returns_422(client):
    response = await client.post("/api/auth/token", data={"username": "geralt@example.com"})

    assert response.status_code == 422


# ---------------------------------------------------------------------------
# GET /api/auth/me
# ---------------------------------------------------------------------------

# A valid token returns its user: id, username and email only.
async def test_me(client, owner):
    response = await client.get("/api/auth/me", headers=owner.headers)

    assert response.status_code == 200
    assert response.json() == {"id": owner.id, "username": "Geralt", "email": "geralt@example.com"}


# No Authorization header, or one that isn't "Bearer ...": oauth2_scheme
# rejects it before the token is read.
@pytest.mark.parametrize(
    "headers",
    [{}, {"Authorization": "Basic Z2VyYWx0OmZha2VwYXNzd29yZA=="}],
    ids=["no header", "basic auth"],
)
async def test_me_without_bearer_token(client, headers):
    response = await client.get("/api/auth/me", headers=headers)

    assert response.status_code == 401
    assert response.json()["detail"] == "Not authenticated"


# Every kind of broken token is rejected with the same 401. Each case gets
# the owner's id, so the token would otherwise point to a real user.
@pytest.mark.parametrize(
    "build_token",
    [
        # "Bearer" with nothing after it passes oauth2_scheme as an empty token.
        lambda user_id: "",
        lambda user_id: "not-a-jwt",
        lambda user_id: make_token(
            {"sub": str(user_id), "exp": in_minutes(30)},
            key="another-secret-key-at-least-32-bytes-long",
        ),
        # alg "none": an unsigned token. The app pins HS256, so it's refused.
        lambda user_id: jwt.encode({"sub": str(user_id), "exp": in_minutes(30)}, None, algorithm="none"),
        lambda user_id: make_token({"sub": str(user_id), "exp": in_minutes(-1)}),
        lambda user_id: make_token({"exp": in_minutes(30)}),
        lambda user_id: make_token({"sub": str(user_id)}),
        lambda user_id: make_token({"sub": "abc", "exp": in_minutes(30)}),
        # PyJWT requires "sub" to be a string.
        lambda user_id: make_token({"sub": user_id, "exp": in_minutes(30)}),
    ],
    ids=[
        "empty",
        "malformed",
        "wrong signature",
        "alg none",
        "expired",
        "no sub",
        "no exp",
        "non-integer sub",
        "sub not a string",
    ],
)
async def test_me_with_invalid_token(client, owner, build_token):
    response = await client.get("/api/auth/me", headers=bearer(build_token(owner.id)))

    assert response.status_code == 401
    assert response.json()["detail"] == "Invalid or expired token"
    assert response.headers["WWW-Authenticate"] == "Bearer"


# A token that was valid when issued stops working once its user is gone.
# There is no delete-user endpoint, so the row is deleted directly.
async def test_me_after_user_is_deleted(client, session, owner):
    await session.execute(delete(models.User).where(models.User.id == owner.id))
    await session.commit()

    response = await client.get("/api/auth/me", headers=owner.headers)

    assert response.status_code == 401
    assert response.json()["detail"] == "User not found"
