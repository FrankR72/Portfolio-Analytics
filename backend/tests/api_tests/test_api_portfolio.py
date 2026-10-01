"""API tests for routers/portfolio.py (/api/portfolios).

Requests go through the real app with an in-memory database (see
conftest.py). Transactions for the analytics routes are inserted directly
with `add_tx`, and prices are patched in services.analytic_service, so
yfinance is never called. The analytics math is covered by
test_analytic_service.py; here each route only gets a happy path with easy
numbers plus the status codes the router adds.

Access by another user (404) and requests without a token (401) are in
test_api_security.py.

Tests that pin known issues (update them when those are fixed):
    - A duplicate name on create returns 406 (it should be 409, like rename).
    - A failed price lookup on /distribution and
      /unrealized_gains_distribution returns 500.
"""

import pandas as pd
import pytest
from httpx import ASGITransport, AsyncClient

from main import app


def closes(prices_by_day: dict) -> pd.Series:
    """Close prices indexed by date, like get_historical_stock_prices returns."""
    return pd.Series(list(prices_by_day.values()), index=pd.to_datetime(list(prices_by_day)))


@pytest.fixture
def current_price(mocker):
    """Fake current price. Set side_effect to a dict's .get (or a function)
    for a different price per symbol."""
    return mocker.patch("services.analytic_service.get_current_stock_price")


@pytest.fixture
def historical_prices(mocker):
    """Fake price history: return_value is a `closes(...)` Series."""
    return mocker.patch("services.analytic_service.get_historical_stock_prices")


# ---------------------------------------------------------------------------
# GET /api/portfolios
# ---------------------------------------------------------------------------

# A new user has no portfolios.
async def test_list_portfolios_empty(client, owner):
    response = await client.get("/api/portfolios", headers=owner.headers)

    assert response.status_code == 200
    assert response.json() == []


# Only your own portfolios are listed, ordered by id.
async def test_list_portfolios_only_yours(client, owner, stranger):
    for name in ["Main", "Retirement"]:
        await client.post("/api/portfolios", json={"name": name}, headers=owner.headers)
    await client.post("/api/portfolios", json={"name": "Ciri's"}, headers=stranger.headers)

    response = await client.get("/api/portfolios", headers=owner.headers)

    assert response.status_code == 200
    assert [p["name"] for p in response.json()] == ["Main", "Retirement"]
    assert all(p["user_id"] == owner.id for p in response.json())


# ---------------------------------------------------------------------------
# POST /api/portfolios
# ---------------------------------------------------------------------------

# 201 with exactly id, name and user_id; the owner is taken from the token.
async def test_create_portfolio(client, owner):
    response = await client.post("/api/portfolios", json={"name": "Main"}, headers=owner.headers)

    assert response.status_code == 201
    body = response.json()
    assert set(body) == {"id", "name", "user_id"}
    assert body["name"] == "Main"
    assert body["user_id"] == owner.id


# Same name in a different case: 406 (see the module docstring).
async def test_create_duplicate_name_is_rejected(client, owner, portfolio):
    response = await client.post("/api/portfolios", json={"name": "MAIN"}, headers=owner.headers)

    assert response.status_code == 406
    assert response.json()["detail"] == "Portfolio name already exists"


# Names only have to be unique per user: another user can use the same one.
async def test_create_same_name_as_another_user(client, stranger, portfolio):
    response = await client.post("/api/portfolios", json={"name": "Main"}, headers=stranger.headers)

    assert response.status_code == 201


# An empty name, or none at all: 422.
@pytest.mark.parametrize("body", [{"name": ""}, {}], ids=["empty name", "no name"])
async def test_create_invalid_body_returns_422(client, owner, body):
    response = await client.post("/api/portfolios", json=body, headers=owner.headers)

    assert response.status_code == 422


# ---------------------------------------------------------------------------
# GET /api/portfolios/{id}
# ---------------------------------------------------------------------------

# Returns the same portfolio that create returned.
async def test_get_portfolio(client, owner, portfolio):
    response = await client.get(f"/api/portfolios/{portfolio['id']}", headers=owner.headers)

    assert response.status_code == 200
    assert response.json() == portfolio


# An id that doesn't exist: 404.
async def test_get_missing_portfolio_returns_404(client, owner):
    response = await client.get("/api/portfolios/999", headers=owner.headers)

    assert response.status_code == 404
    assert response.json()["detail"] == "Portfolio not found"


# A path id that isn't an integer: 422 from FastAPI's path validation.
async def test_get_portfolio_non_integer_id_returns_422(client, owner):
    response = await client.get("/api/portfolios/abc", headers=owner.headers)

    assert response.status_code == 422


# ---------------------------------------------------------------------------
# PUT /api/portfolios/{id}
# ---------------------------------------------------------------------------

# Rename: 200 with the new name. Surrounding spaces are stripped
# (str_strip_whitespace in PortfolioUpdate).
async def test_rename_portfolio(client, owner, portfolio):
    response = await client.put(
        f"/api/portfolios/{portfolio['id']}", json={"name": "  Long term  "}, headers=owner.headers
    )

    assert response.status_code == 200
    assert response.json() == {**portfolio, "name": "Long term"}


# Changing only the case of its own name is allowed: the duplicate check
# skips the portfolio being renamed.
async def test_rename_portfolio_to_its_own_name(client, owner, portfolio):
    response = await client.put(
        f"/api/portfolios/{portfolio['id']}", json={"name": "MAIN"}, headers=owner.headers
    )

    assert response.status_code == 200
    assert response.json()["name"] == "MAIN"


# The name of another of your portfolios, in a different case: 409.
async def test_rename_to_duplicate_name_is_rejected(client, owner, portfolio):
    await client.post("/api/portfolios", json={"name": "Retirement"}, headers=owner.headers)

    response = await client.put(
        f"/api/portfolios/{portfolio['id']}", json={"name": "retirement"}, headers=owner.headers
    )

    assert response.status_code == 409
    assert response.json()["detail"] == "You already have a portfolio with that name"


# PortfolioUpdate forbids unknown fields, so the owner can't be changed
# through the body: 422.
async def test_rename_with_extra_field_returns_422(client, owner, stranger, portfolio):
    response = await client.put(
        f"/api/portfolios/{portfolio['id']}",
        json={"name": "Main", "user_id": stranger.id},
        headers=owner.headers,
    )

    assert response.status_code == 422


# Only spaces: empty after stripping, so 422.
async def test_rename_to_blank_name_returns_422(client, owner, portfolio):
    response = await client.put(
        f"/api/portfolios/{portfolio['id']}", json={"name": "   "}, headers=owner.headers
    )

    assert response.status_code == 422


# An id that doesn't exist: 404.
async def test_rename_missing_portfolio_returns_404(client, owner):
    response = await client.put("/api/portfolios/999", json={"name": "Main"}, headers=owner.headers)

    assert response.status_code == 404


# ---------------------------------------------------------------------------
# DELETE /api/portfolios/{id}
# ---------------------------------------------------------------------------

# 204 with an empty body; the portfolio is gone and so are its transactions.
async def test_delete_portfolio(client, owner, portfolio, add_tx, count_transactions):
    await add_tx(portfolio, "AAPL", "BUY", 10, 100.0, "2026-01-05")

    response = await client.delete(f"/api/portfolios/{portfolio['id']}", headers=owner.headers)

    assert response.status_code == 204
    assert response.content == b""
    follow_up = await client.get(f"/api/portfolios/{portfolio['id']}", headers=owner.headers)
    assert follow_up.status_code == 404
    assert await count_transactions(portfolio) == 0


# An id that doesn't exist: 404.
async def test_delete_missing_portfolio_returns_404(client, owner):
    response = await client.delete("/api/portfolios/999", headers=owner.headers)

    assert response.status_code == 404


# ---------------------------------------------------------------------------
# GET /api/portfolios/{id}/distribution
# ---------------------------------------------------------------------------

# AAPL: 10 shares at 150 = 1500. MSFT: 5 shares at 100 = 500. Total 2000,
# so 75% and 25%. TSLA was fully sold, so it's left out.
async def test_distribution(client, owner, portfolio, add_tx, current_price):
    await add_tx(portfolio, "AAPL", "BUY", 10, 100.0, "2026-01-05")
    await add_tx(portfolio, "MSFT", "BUY", 5, 200.0, "2026-01-05")
    await add_tx(portfolio, "TSLA", "BUY", 2, 50.0, "2026-01-05")
    await add_tx(portfolio, "TSLA", "SELL", 2, 60.0, "2026-01-06")
    current_price.side_effect = {"AAPL": 150.0, "MSFT": 100.0}.get

    response = await client.get(f"/api/portfolios/{portfolio['id']}/distribution", headers=owner.headers)

    assert response.status_code == 200
    assert response.json() == {
        "total_value": 2000.0,
        "distribution": {
            "AAPL": {"current_value": 1500.0, "distribution_percentage": 75.0},
            "MSFT": {"current_value": 500.0, "distribution_percentage": 25.0},
        },
    }


# No transactions: total 0 and no positions.
async def test_distribution_empty_portfolio(client, owner, portfolio):
    response = await client.get(f"/api/portfolios/{portfolio['id']}/distribution", headers=owner.headers)

    assert response.status_code == 200
    assert response.json() == {"total_value": 0.0, "distribution": {}}


# A SELL with no shares held makes the history invalid: 400.
async def test_distribution_invalid_history_returns_400(client, owner, portfolio, add_tx):
    await add_tx(portfolio, "AAPL", "SELL", 1, 100.0, "2026-01-05")

    response = await client.get(f"/api/portfolios/{portfolio['id']}/distribution", headers=owner.headers)

    assert response.status_code == 400


# ---------------------------------------------------------------------------
# GET /api/portfolios/{id}/unrealized_gains_distribution
# ---------------------------------------------------------------------------

# AAPL: 10 * 150 - 1000 = +500. MSFT: 5 * 100 - 1000 = -500.
async def test_unrealized_gains_distribution(client, owner, portfolio, add_tx, current_price):
    await add_tx(portfolio, "AAPL", "BUY", 10, 100.0, "2026-01-05")
    await add_tx(portfolio, "MSFT", "BUY", 5, 200.0, "2026-01-05")
    current_price.side_effect = {"AAPL": 150.0, "MSFT": 100.0}.get

    response = await client.get(
        f"/api/portfolios/{portfolio['id']}/unrealized_gains_distribution", headers=owner.headers
    )

    assert response.status_code == 200
    assert response.json() == {
        "unrealized_gains_distribution": {
            "AAPL": {"unrealized_gain_loss": 500.0},
            "MSFT": {"unrealized_gain_loss": -500.0},
        }
    }


# ---------------------------------------------------------------------------
# Failed price lookup on both distribution routes
# ---------------------------------------------------------------------------

# get_current_stock_price raises ValueError and neither route catches it, so
# the client gets a 500 (see the module docstring). This test uses its own
# client with raise_app_exceptions=False to see the response a real client
# would get, instead of the exception.
@pytest.mark.parametrize("route", ["distribution", "unrealized_gains_distribution"])
async def test_failed_price_lookup_returns_500(client, owner, portfolio, add_tx, current_price, route):
    await add_tx(portfolio, "AAPL", "BUY", 10, 100.0, "2026-01-05")
    current_price.side_effect = ValueError("No price history")

    transport = ASGITransport(app=app, raise_app_exceptions=False)
    async with AsyncClient(transport=transport, base_url="http://test") as raw_client:
        response = await raw_client.get(f"/api/portfolios/{portfolio['id']}/{route}", headers=owner.headers)

    assert response.status_code == 500


# ---------------------------------------------------------------------------
# GET /api/portfolios/{id}/performance
# ---------------------------------------------------------------------------

# 10 AAPL bought at 100 on Monday 2026-01-05. Closes: 100 on Monday, 110 on
# Tuesday. Monday: 1000 / 1000 invested = 0%. Tuesday: 1100 / 1000 = +10%.
async def test_performance(client, owner, portfolio, add_tx, historical_prices):
    await add_tx(portfolio, "AAPL", "BUY", 10, 100.0, "2026-01-05")
    historical_prices.return_value = closes({"2026-01-05": 100.0, "2026-01-06": 110.0})

    response = await client.get(
        f"/api/portfolios/{portfolio['id']}/performance",
        params={"start_date": "2026-01-05", "end_date": "2026-01-06"},
        headers=owner.headers,
    )

    assert response.status_code == 200
    body = response.json()
    assert [p["date"] for p in body["points"]] == ["2026-01-05", "2026-01-06"]
    assert [p["holdings_value"] for p in body["points"]] == [1000.0, 1100.0]
    assert [p["return_percentage"] for p in body["points"]] == pytest.approx([0.0, 10.0])


# No transactions: an empty series, and no prices are fetched.
async def test_performance_empty_portfolio(client, owner, portfolio, historical_prices):
    response = await client.get(
        f"/api/portfolios/{portfolio['id']}/performance",
        params={"start_date": "2026-01-05", "end_date": "2026-01-06"},
        headers=owner.headers,
    )

    assert response.status_code == 200
    assert response.json()["points"] == []
    historical_prices.assert_not_called()


# start after end, or end in the future: the service's ValueError becomes
# a 422 with its message (the conversion the router adds).
@pytest.mark.parametrize(
    "start_date, end_date",
    [("2026-01-06", "2026-01-05"), ("2026-01-05", "2099-01-01")],
    ids=["start after end", "end in the future"],
)
async def test_performance_invalid_range_returns_422(client, owner, portfolio, start_date, end_date):
    response = await client.get(
        f"/api/portfolios/{portfolio['id']}/performance",
        params={"start_date": start_date, "end_date": end_date},
        headers=owner.headers,
    )

    assert response.status_code == 422
    assert response.json()["detail"] == "Use start <= end, with end no later than today"


# A stock split in the window (or any other ValueError while computing
# the series) is also a 422 with the message.
async def test_performance_split_returns_422(client, owner, portfolio, add_tx, historical_prices):
    await add_tx(portfolio, "AAPL", "BUY", 10, 100.0, "2026-01-05")
    historical_prices.side_effect = ValueError("Could not verify a usable price for AAPL")

    response = await client.get(
        f"/api/portfolios/{portfolio['id']}/performance",
        params={"start_date": "2026-01-05", "end_date": "2026-01-06"},
        headers=owner.headers,
    )

    assert response.status_code == 422
    assert response.json()["detail"] == "Could not verify a usable price for AAPL"


# Missing or malformed dates are rejected by FastAPI before the route runs.
@pytest.mark.parametrize(
    "params",
    [{}, {"start_date": "2026-01-05"}, {"start_date": "2026-13-01", "end_date": "2026-01-06"}],
    ids=["no dates", "no end date", "invalid month"],
)
async def test_performance_bad_query_returns_422(client, owner, portfolio, params):
    response = await client.get(
        f"/api/portfolios/{portfolio['id']}/performance", params=params, headers=owner.headers
    )

    assert response.status_code == 422


# ---------------------------------------------------------------------------
# GET /api/portfolios/{id}/stocks_performance
# ---------------------------------------------------------------------------

# Same numbers as test_performance, grouped under the symbol, with no errors.
async def test_stocks_performance(client, owner, portfolio, add_tx, historical_prices):
    await add_tx(portfolio, "AAPL", "BUY", 10, 100.0, "2026-01-05")
    historical_prices.return_value = closes({"2026-01-05": 100.0, "2026-01-06": 110.0})

    response = await client.get(
        f"/api/portfolios/{portfolio['id']}/stocks_performance",
        params={"start_date": "2026-01-05", "end_date": "2026-01-06"},
        headers=owner.headers,
    )

    assert response.status_code == 200
    body = response.json()
    assert list(body["stocks"]) == ["AAPL"]
    assert body["errors"] == {}
    points = body["stocks"]["AAPL"]["points"]
    assert [p["return_percentage"] for p in points] == pytest.approx([0.0, 10.0])


# A stock whose prices fail goes to "errors" instead of failing the request.
async def test_stocks_performance_failed_stock_goes_to_errors(client, owner, portfolio, add_tx, historical_prices):
    await add_tx(portfolio, "AAPL", "BUY", 10, 100.0, "2026-01-05")
    historical_prices.side_effect = ValueError("Could not verify a usable price for AAPL")

    response = await client.get(
        f"/api/portfolios/{portfolio['id']}/stocks_performance",
        params={"start_date": "2026-01-05", "end_date": "2026-01-06"},
        headers=owner.headers,
    )

    assert response.status_code == 200
    assert response.json()["stocks"] == {}
    assert response.json()["errors"] == {"AAPL": "Could not verify a usable price for AAPL"}


# An invalid date range: 422 with the service's message.
async def test_stocks_performance_invalid_range_returns_422(client, owner, portfolio):
    response = await client.get(
        f"/api/portfolios/{portfolio['id']}/stocks_performance",
        params={"start_date": "2026-01-06", "end_date": "2026-01-05"},
        headers=owner.headers,
    )

    assert response.status_code == 422
    assert response.json()["detail"] == "Use start <= end, with end no later than today"
