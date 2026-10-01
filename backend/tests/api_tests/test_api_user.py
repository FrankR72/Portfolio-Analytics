"""API tests for routers/user.py (POST /api/users, sign-up).

Requests go through the real app with an in-memory database (see
conftest.py). The service tests already cover the lookup logic; these check
what the HTTP layer adds: the 201 status, the response body filtered by
response_model, Pydantic's 422 for an invalid body, and that no token is
needed.

The duplicate-username test expects 406, the current status code. It is a
known issue (it should be 409), so update the test when that is fixed.
"""

from sqlalchemy import func, select

from models import models


async def count_users(session):
    """Number of users in the database. Used to check that a rejected
    sign-up didn't insert anything."""
    return await session.scalar(select(func.count()).select_from(models.User))


# ---------------------------------------------------------------------------
# POST /api/users
# ---------------------------------------------------------------------------

# Sign-up is public (no Authorization header) and returns 201 with only id,
# username and email: never the password or its hash. The email is stored
# lowercased.
async def test_create_user(client, session):
    response = await client.post(
        "/api/users",
        json={"username": "Geralt", "email": "Geralt@Example.com", "password": "fakepassword"},
    )

    assert response.status_code == 201
    body = response.json()
    assert set(body) == {"id", "username", "email"}
    assert body["username"] == "Geralt"
    assert body["email"] == "geralt@example.com"
    assert await count_users(session) == 1


# Same username in a different case: 406 (see the module docstring), and the
# second user is not inserted.
async def test_duplicate_username_is_rejected(client, session, create_user):
    await create_user(username="Geralt", email="geralt@example.com")

    response = await client.post(
        "/api/users",
        json={"username": "GERALT", "email": "other@example.com", "password": "fakepassword"},
    )

    assert response.status_code == 406
    assert response.json()["detail"] == "Username already exists"
    assert await count_users(session) == 1


# Same email in a different case: 400, and the second user is not inserted.
async def test_duplicate_email_is_rejected(client, session, create_user):
    await create_user(username="Geralt", email="geralt@example.com")

    response = await client.post(
        "/api/users",
        json={"username": "Ciri", "email": "GERALT@example.com", "password": "fakepassword"},
    )

    assert response.status_code == 400
    assert response.json()["detail"] == "Email already registered"
    assert await count_users(session) == 1


# Missing fields: Pydantic rejects the body with 422 before the service runs,
# and the error names each missing field.
async def test_missing_fields_return_422(client, session):
    response = await client.post("/api/users", json={"username": "Geralt"})

    assert response.status_code == 422
    missing = {error["loc"][-1] for error in response.json()["detail"]}
    assert missing == {"email", "password"}
    assert await count_users(session) == 0


# A 7-character password is one short of the minimum (8): 422.
async def test_short_password_returns_422(client, session):
    response = await client.post(
        "/api/users",
        json={"username": "Geralt", "email": "geralt@example.com", "password": "1234567"},
    )

    assert response.status_code == 422
    assert response.json()["detail"][0]["loc"] == ["body", "password"]
    assert await count_users(session) == 0


# An email without "@" fails EmailStr validation: 422.
async def test_invalid_email_returns_422(client, session):
    response = await client.post(
        "/api/users",
        json={"username": "Geralt", "email": "not-an-email", "password": "fakepassword"},
    )

    assert response.status_code == 422
    assert response.json()["detail"][0]["loc"] == ["body", "email"]
    assert await count_users(session) == 0


# The user created by sign-up can log in right away with the same
# credentials (what the frontend's signup page does next).
async def test_new_user_can_log_in(create_user, login):
    await create_user(email="geralt@example.com", password="fakepassword")

    headers = await login(email="geralt@example.com", password="fakepassword")

    assert headers["Authorization"].startswith("Bearer ")
