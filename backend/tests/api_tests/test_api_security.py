"""Authentication and authorization checks across every protected route.

Requests go through the real app with an in-memory database (see
conftest.py). The other API test files check what each route does; this one
checks, for every route at once, that:
    - without a valid token, it returns 401 (authentication),
    - another user's portfolio is answered with 404, not 403, so its
      existence isn't revealed (authorization),
and that neither case changes the owner's data.

How the bad tokens are rejected (expired, tampered, alg "none"...) is
tested once in test_api_auth.py, since every route uses the same
get_current_user dependency. Here one invalid token is enough.

ROUTES lists every protected route. test_routes_list_is_complete fails when
a route is added to the app but not to ROUTES, so a new route that forgets
Depends(get_current_user) can't go unnoticed. Sign-up and login are public
and tested in test_api_user.py and test_api_auth.py.
"""

import pytest
from sqlalchemy import select

from main import app
from models import models


BUY = {"symbol": "AAPL", "transaction_type": "BUY", "quantity_actions": 1, "price": 100.0}
DATES = {"start_date": "2026-01-05", "end_date": "2026-01-06"}

# (method, path, query params, JSON body). "{portfolio_id}" and
# "{transaction_id}" are filled in with the owner's portfolio and
# transaction, in the path and in the query params.
ROUTES = [
    ("GET", "/api/auth/me", {}, None),
    ("GET", "/api/portfolios", {}, None),
    ("POST", "/api/portfolios", {}, {"name": "New"}),
    ("GET", "/api/portfolios/{portfolio_id}", {}, None),
    ("PUT", "/api/portfolios/{portfolio_id}", {}, {"name": "Hacked"}),
    ("DELETE", "/api/portfolios/{portfolio_id}", {}, None),
    ("GET", "/api/portfolios/{portfolio_id}/distribution", {}, None),
    ("GET", "/api/portfolios/{portfolio_id}/unrealized_gains_distribution", {}, None),
    ("GET", "/api/portfolios/{portfolio_id}/performance", DATES, None),
    ("GET", "/api/portfolios/{portfolio_id}/stocks_performance", DATES, None),
    ("POST", "/api/transactions", {"portfolio_id": "{portfolio_id}"}, BUY),
    ("GET", "/api/transactions", {"portfolio_id": "{portfolio_id}"}, None),
    ("GET", "/api/transactions/closed", {"portfolio_id": "{portfolio_id}"}, None),
    ("DELETE", "/api/transactions/{transaction_id}", {"portfolio_id": "{portfolio_id}"}, None),
    ("GET", "/api/holdings/{portfolio_id}", {}, None),
]

# Routes that work on one portfolio, and so must refuse another user's.
PORTFOLIO_ROUTES = [
    route for route in ROUTES
    if "{portfolio_id}" in route[1] or "{portfolio_id}" in route[2].values()
]

# The "/" welcome message is public too, but it's hidden from the schema
# (include_in_schema=False), so it doesn't need to be listed.
PUBLIC_ROUTES = {
    ("POST", "/api/users"),
    ("POST", "/api/auth/token"),
}


def route_id(route) -> str:
    return f"{route[0]} {route[1]}"


@pytest.fixture(autouse=True)
def ticker_validation(mocker):
    """Every ticker is recognized, so a POST that skipped the checks would
    really create a row (and the "nothing was created" checks mean something)."""
    return mocker.patch("services.transaction_service.ticker_validation", return_value=True)


@pytest.fixture
async def owner_data(portfolio, add_tx):
    """The owner's portfolio with one BUY, the ids every route needs."""
    transaction_id = await add_tx(portfolio, "AAPL", "BUY", 10, 100.0, "2026-01-05")
    return {"portfolio_id": portfolio["id"], "transaction_id": transaction_id}


async def send(client, route, ids, headers):
    """Send one ROUTES entry with the ids filled in."""
    method, path, params, body = route
    params = {key: value.format(**ids) if isinstance(value, str) else value for key, value in params.items()}
    return await client.request(method, path.format(**ids), params=params, json=body, headers=headers)


async def assert_owner_data_unchanged(session, owner, owner_data):
    """The owner still has exactly the portfolio "Main" with its one BUY."""
    session.expire_all()
    portfolios = (await session.execute(select(models.Portfolio))).scalars().all()
    assert [(p.id, p.name, p.user_id) for p in portfolios] == [(owner_data["portfolio_id"], "Main", owner.id)]
    transactions = (await session.execute(select(models.Transaction.id))).scalars().all()
    assert transactions == [owner_data["transaction_id"]]


# ---------------------------------------------------------------------------
# ROUTES covers the whole app
# ---------------------------------------------------------------------------

# Every route of the app is either public or in ROUTES. If this fails after
# adding an endpoint, add it to ROUTES (or to PUBLIC_ROUTES if it really
# needs no login). The routes are read from the OpenAPI schema (what /docs
# shows), because app.routes doesn't list the included routers' routes.
def test_routes_list_is_complete():
    app_routes = {
        (method.upper(), path)
        for path, operations in app.openapi()["paths"].items()
        for method in operations
    }
    listed = {(method, path) for method, path, _, _ in ROUTES}

    assert app_routes - PUBLIC_ROUTES == listed


# ---------------------------------------------------------------------------
# Authentication: 401 without a valid token
# ---------------------------------------------------------------------------

# No Authorization header: 401, and the owner's data is untouched.
@pytest.mark.parametrize("route", ROUTES, ids=route_id)
async def test_route_without_token_returns_401(client, session, owner, owner_data, route):
    response = await send(client, route, owner_data, headers={})

    assert response.status_code == 401
    await assert_owner_data_unchanged(session, owner, owner_data)


# A token that isn't valid: 401, and the owner's data is untouched.
@pytest.mark.parametrize("route", ROUTES, ids=route_id)
async def test_route_with_invalid_token_returns_401(client, session, owner, owner_data, route):
    response = await send(client, route, owner_data, headers={"Authorization": "Bearer not-a-jwt"})

    assert response.status_code == 401
    await assert_owner_data_unchanged(session, owner, owner_data)


# ---------------------------------------------------------------------------
# Authorization: another user's portfolio is 404
# ---------------------------------------------------------------------------

# A logged-in stranger gets 404 on the owner's portfolio, as if it didn't
# exist, and can't change it (rename, delete, add or delete transactions).
@pytest.mark.parametrize("route", PORTFOLIO_ROUTES, ids=route_id)
async def test_other_users_portfolio_returns_404(client, session, owner, stranger, owner_data, route):
    response = await send(client, route, owner_data, headers=stranger.headers)

    assert response.status_code == 404
    assert response.json()["detail"] in {"Portfolio not found", "Transaction not found"}
    await assert_owner_data_unchanged(session, owner, owner_data)


# The stranger's list of portfolios doesn't include the owner's.
async def test_other_users_portfolios_are_not_listed(client, stranger, owner_data):
    response = await client.get("/api/portfolios", headers=stranger.headers)

    assert response.status_code == 200
    assert response.json() == []
