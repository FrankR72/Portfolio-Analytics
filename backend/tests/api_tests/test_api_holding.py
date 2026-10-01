"""API tests for routers/holding.py (GET /api/holdings/{portfolio_id}).

Requests go through the real app with an in-memory database (see
conftest.py). Transactions are inserted directly with `add_tx`, and the
current price is patched in services.holding_service, so yfinance is never
called.

Access by another user (404) and requests without a token (401) are in
test_api_security.py.
"""

import pytest


@pytest.fixture
def current_price(mocker):
    """Fake current price. Set side_effect to a dict's .get (or a function)
    for a different price per symbol."""
    return mocker.patch("services.holding_service.get_current_stock_price")


# ---------------------------------------------------------------------------
# GET /api/holdings/{portfolio_id}
# ---------------------------------------------------------------------------

# AAPL: 10 at 100 + 10 at 200 = 20 shares, cost 3000, average 150. At 180:
# value 3600, gain 600, return 600 / 3000 = 20%. TSLA was fully sold, so
# it's left out.
async def test_holdings(client, owner, portfolio, add_tx, current_price):
    await add_tx(portfolio, "AAPL", "BUY", 10, 100.0, "2026-01-05")
    await add_tx(portfolio, "AAPL", "BUY", 10, 200.0, "2026-01-06")
    await add_tx(portfolio, "TSLA", "BUY", 2, 50.0, "2026-01-05")
    await add_tx(portfolio, "TSLA", "SELL", 2, 60.0, "2026-01-06")
    current_price.side_effect = {"AAPL": 180.0}.get

    response = await client.get(f"/api/holdings/{portfolio['id']}", headers=owner.headers)

    assert response.status_code == 200
    assert response.json() == [
        {
            "symbol": "AAPL",
            "number_current_shares": 20,
            "avg_cost_per_share": 150.0,
            "cost_bases": 3000.0,
            "current_price_per_share": 180.0,
            "current_value": 3600.0,
            "unrealized_gain_loss": 600.0,
            "return_percentage": pytest.approx(20.0),
        }
    ]


# A failed price lookup doesn't fail the request: the live fields of that
# symbol are null and the cost fields are still there.
async def test_holdings_failed_price_lookup(client, owner, portfolio, add_tx, current_price):
    await add_tx(portfolio, "AAPL", "BUY", 10, 100.0, "2026-01-05")
    current_price.side_effect = ValueError("No price history")

    response = await client.get(f"/api/holdings/{portfolio['id']}", headers=owner.headers)

    assert response.status_code == 200
    [holding] = response.json()
    assert holding["cost_bases"] == 1000.0
    assert holding["current_price_per_share"] is None
    assert holding["current_value"] is None
    assert holding["unrealized_gain_loss"] is None
    assert holding["return_percentage"] is None


# No transactions: no holdings, and no prices are fetched.
async def test_holdings_empty_portfolio(client, owner, portfolio, current_price):
    response = await client.get(f"/api/holdings/{portfolio['id']}", headers=owner.headers)

    assert response.status_code == 200
    assert response.json() == []
    current_price.assert_not_called()


# A SELL with no shares held makes the history invalid: 400.
async def test_holdings_invalid_history_returns_400(client, owner, portfolio, add_tx):
    await add_tx(portfolio, "AAPL", "SELL", 1, 100.0, "2026-01-05")

    response = await client.get(f"/api/holdings/{portfolio['id']}", headers=owner.headers)

    assert response.status_code == 400


# A portfolio that doesn't exist: 404.
async def test_holdings_missing_portfolio_returns_404(client, owner):
    response = await client.get("/api/holdings/999", headers=owner.headers)

    assert response.status_code == 404
    assert response.json()["detail"] == "Portfolio not found"
