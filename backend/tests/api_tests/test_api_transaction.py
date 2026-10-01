"""API tests for routers/transaction.py (/api/transactions).

Requests go through the real app with an in-memory database (see
conftest.py). The ticker check is patched in services.transaction_service,
so yfinance is never called. Existing history is inserted directly with
`add_tx`; new transactions go through POST so its checks run.

Access by another user (404) and requests without a token (401) are in
test_api_security.py.

Tests that pin known issues (update them when those are fixed):
    - Creating a transaction returns 200 (it should be 201).
    - The list is ordered by id, so a backdated transaction comes last.
"""

from datetime import UTC, datetime

import pytest


@pytest.fixture
def ticker_validation(mocker):
    """Fake ticker check. Every ticker is recognized unless a test sets
    return_value to False."""
    return mocker.patch("services.transaction_service.ticker_validation", return_value=True)


def buy(symbol="AAPL", qty=10, price=100.0, day=None) -> dict:
    """Body for POST /api/transactions. Without `day`, the date is omitted."""
    body = {"symbol": symbol, "transaction_type": "BUY", "quantity_actions": qty, "price": price}
    if day is not None:
        body["transaction_date"] = day
    return body


def sell(symbol="AAPL", qty=10, price=100.0, day=None) -> dict:
    return {**buy(symbol, qty, price, day), "transaction_type": "SELL"}


# ---------------------------------------------------------------------------
# POST /api/transactions
# ---------------------------------------------------------------------------

# 200 (see the module docstring) with the stored transaction. The symbol is
# stripped and uppercased before the ticker check, total_value is
# 10 * 100.5 = 1005, and a given date is stored as midnight UTC.
async def test_create_transaction(client, owner, portfolio, ticker_validation, count_transactions):
    response = await client.post(
        "/api/transactions",
        params={"portfolio_id": portfolio["id"]},
        json=buy(symbol=" aapl ", qty=10, price=100.5, day="2026-01-05"),
        headers=owner.headers,
    )

    assert response.status_code == 200
    body = response.json()
    assert set(body) == {
        "id", "symbol", "transaction_type", "quantity_actions", "price",
        "total_value", "transaction_date", "portfolio_id",
    }
    assert body["symbol"] == "AAPL"
    assert body["transaction_type"] == "BUY"
    assert body["total_value"] == 1005.0
    assert body["portfolio_id"] == portfolio["id"]
    assert body["transaction_date"].startswith("2026-01-05T00:00:00")
    ticker_validation.assert_called_once_with("AAPL")
    assert await count_transactions(portfolio) == 1


# Without a date, the transaction is dated now (today in UTC).
async def test_create_transaction_without_date(client, owner, portfolio, ticker_validation):
    response = await client.post(
        "/api/transactions", params={"portfolio_id": portfolio["id"]}, json=buy(), headers=owner.headers
    )

    assert response.status_code == 200
    assert response.json()["transaction_date"].startswith(datetime.now(UTC).date().isoformat())


# A SELL covered by the shares held at its date is accepted.
async def test_create_covered_sell(client, owner, portfolio, add_tx, ticker_validation):
    await add_tx(portfolio, "AAPL", "BUY", 10, 100.0, "2026-01-05")

    response = await client.post(
        "/api/transactions",
        params={"portfolio_id": portfolio["id"]},
        json=sell(qty=10, price=120.0, day="2026-01-06"),
        headers=owner.headers,
    )

    assert response.status_code == 200


# Selling more than is held, or selling before the shares were bought
# (backdated): 400, and nothing is stored.
@pytest.mark.parametrize(
    "body",
    [sell(qty=11, day="2026-01-06"), sell(qty=5, day="2026-01-04")],
    ids=["more than held", "before the buy"],
)
async def test_create_oversell_is_rejected(client, owner, portfolio, add_tx, ticker_validation, count_transactions, body):
    await add_tx(portfolio, "AAPL", "BUY", 10, 100.0, "2026-01-05")

    response = await client.post(
        "/api/transactions", params={"portfolio_id": portfolio["id"]}, json=body, headers=owner.headers
    )

    assert response.status_code == 400
    assert response.json()["detail"] == "Not enough shares to sell on that date"
    assert await count_transactions(portfolio) == 1


# A ticker yfinance doesn't recognize: 422, and nothing is stored.
async def test_create_unknown_ticker_is_rejected(client, owner, portfolio, ticker_validation, count_transactions):
    ticker_validation.return_value = False

    response = await client.post(
        "/api/transactions",
        params={"portfolio_id": portfolio["id"]},
        json=buy(symbol="NOPE"),
        headers=owner.headers,
    )

    assert response.status_code == 422
    assert response.json()["detail"].startswith("Ticker not recognized")
    assert await count_transactions(portfolio) == 0


# Invalid bodies are rejected by Pydantic before the ticker is checked.
@pytest.mark.parametrize(
    "body",
    [
        buy(qty=0),
        buy(price=-1.0),
        buy(symbol=""),
        {**buy(), "transaction_type": "HOLD"},
        {**buy(), "quantity_actions": 1.5},
        {"symbol": "AAPL"},
    ],
    ids=["zero shares", "negative price", "empty symbol", "unknown type", "fractional shares", "missing fields"],
)
async def test_create_invalid_body_returns_422(client, owner, portfolio, ticker_validation, body):
    response = await client.post(
        "/api/transactions", params={"portfolio_id": portfolio["id"]}, json=body, headers=owner.headers
    )

    assert response.status_code == 422
    ticker_validation.assert_not_called()


# portfolio_id is a required query parameter: 422 without it.
async def test_create_without_portfolio_id_returns_422(client, owner, ticker_validation):
    response = await client.post("/api/transactions", json=buy(), headers=owner.headers)

    assert response.status_code == 422


# A portfolio that doesn't exist: 404.
async def test_create_in_missing_portfolio_returns_404(client, owner, ticker_validation):
    response = await client.post(
        "/api/transactions", params={"portfolio_id": 999}, json=buy(), headers=owner.headers
    )

    assert response.status_code == 404
    assert response.json()["detail"] == "Portfolio not found"


# ---------------------------------------------------------------------------
# GET /api/transactions
# ---------------------------------------------------------------------------

# Ordered by id, not date: the backdated BUY (inserted last) comes last
# (see the module docstring).
async def test_list_transactions(client, owner, portfolio, add_tx):
    first = await add_tx(portfolio, "AAPL", "BUY", 10, 100.0, "2026-01-05")
    backdated = await add_tx(portfolio, "MSFT", "BUY", 5, 200.0, "2026-01-01")

    response = await client.get(
        "/api/transactions", params={"portfolio_id": portfolio["id"]}, headers=owner.headers
    )

    assert response.status_code == 200
    assert [t["id"] for t in response.json()] == [first, backdated]


# Only that portfolio's transactions are listed.
async def test_list_transactions_of_one_portfolio(client, owner, portfolio, add_tx):
    other = (await client.post("/api/portfolios", json={"name": "Other"}, headers=owner.headers)).json()
    mine = await add_tx(portfolio, "AAPL", "BUY", 10, 100.0, "2026-01-05")
    await add_tx(other, "MSFT", "BUY", 5, 200.0, "2026-01-05")

    response = await client.get(
        "/api/transactions", params={"portfolio_id": portfolio["id"]}, headers=owner.headers
    )

    assert [t["id"] for t in response.json()] == [mine]


# A portfolio without transactions: an empty list.
async def test_list_transactions_empty(client, owner, portfolio):
    response = await client.get(
        "/api/transactions", params={"portfolio_id": portfolio["id"]}, headers=owner.headers
    )

    assert response.status_code == 200
    assert response.json() == []


# A portfolio that doesn't exist: 404.
async def test_list_transactions_missing_portfolio_returns_404(client, owner):
    response = await client.get("/api/transactions", params={"portfolio_id": 999}, headers=owner.headers)

    assert response.status_code == 404


# ---------------------------------------------------------------------------
# GET /api/transactions/closed
# ---------------------------------------------------------------------------

# Buy 10 at 100 and 10 at 200: average cost 150. Sell 5 at 180:
# cost 5 * 150 = 750, proceeds 5 * 180 = 900, gain 150, return 150 / 750 = 20%.
async def test_closed_transactions(client, owner, portfolio, add_tx):
    await add_tx(portfolio, "AAPL", "BUY", 10, 100.0, "2026-01-05")
    await add_tx(portfolio, "AAPL", "BUY", 10, 200.0, "2026-01-06")
    await add_tx(portfolio, "AAPL", "SELL", 5, 180.0, "2026-01-07")

    response = await client.get(
        "/api/transactions/closed", params={"portfolio_id": portfolio["id"]}, headers=owner.headers
    )

    assert response.status_code == 200
    [closed] = response.json()
    assert closed["transaction_date"].startswith("2026-01-07")
    assert {key: value for key, value in closed.items() if key != "transaction_date"} == {
        "symbol": "AAPL",
        "number_shares_sold": 5,
        "avg_cost_per_share": 150.0,
        "sold_price_per_share": 180.0,
        "total_cost_of_shares_sold": 750.0,
        "total_sold_price": 900.0,
        "realized_gain_loss": 150.0,
        "return_percentage": pytest.approx(20.0),
    }


# Only BUYs: nothing has been realized yet.
async def test_closed_transactions_without_sells(client, owner, portfolio, add_tx):
    await add_tx(portfolio, "AAPL", "BUY", 10, 100.0, "2026-01-05")

    response = await client.get(
        "/api/transactions/closed", params={"portfolio_id": portfolio["id"]}, headers=owner.headers
    )

    assert response.status_code == 200
    assert response.json() == []


# A SELL with no shares held makes the history invalid: 400.
async def test_closed_transactions_invalid_history_returns_400(client, owner, portfolio, add_tx):
    await add_tx(portfolio, "AAPL", "SELL", 1, 100.0, "2026-01-05")

    response = await client.get(
        "/api/transactions/closed", params={"portfolio_id": portfolio["id"]}, headers=owner.headers
    )

    assert response.status_code == 400


# ---------------------------------------------------------------------------
# DELETE /api/transactions/{transaction_id}
# ---------------------------------------------------------------------------

# Deleting a SELL is always allowed: 204 with an empty body, and the row is gone.
async def test_delete_sell(client, owner, portfolio, add_tx, count_transactions):
    await add_tx(portfolio, "AAPL", "BUY", 10, 100.0, "2026-01-05")
    sale = await add_tx(portfolio, "AAPL", "SELL", 10, 120.0, "2026-01-06")

    response = await client.delete(
        f"/api/transactions/{sale}", params={"portfolio_id": portfolio["id"]}, headers=owner.headers
    )

    assert response.status_code == 204
    assert response.content == b""
    assert await count_transactions(portfolio) == 1


# A BUY that a later SELL needs: 409, and nothing is deleted.
async def test_delete_needed_buy_is_rejected(client, owner, portfolio, add_tx, count_transactions):
    purchase = await add_tx(portfolio, "AAPL", "BUY", 10, 100.0, "2026-01-05")
    await add_tx(portfolio, "AAPL", "SELL", 10, 120.0, "2026-01-06")

    response = await client.delete(
        f"/api/transactions/{purchase}", params={"portfolio_id": portfolio["id"]}, headers=owner.headers
    )

    assert response.status_code == 409
    assert response.json()["detail"] == "Deleting this BUY would leave a later SELL without enough shares"
    assert await count_transactions(portfolio) == 2


# A BUY whose shares the SELL doesn't need (another BUY covers it): 204.
async def test_delete_unneeded_buy(client, owner, portfolio, add_tx, count_transactions):
    await add_tx(portfolio, "AAPL", "BUY", 10, 100.0, "2026-01-05")
    extra = await add_tx(portfolio, "AAPL", "BUY", 10, 110.0, "2026-01-05")
    await add_tx(portfolio, "AAPL", "SELL", 10, 120.0, "2026-01-06")

    response = await client.delete(
        f"/api/transactions/{extra}", params={"portfolio_id": portfolio["id"]}, headers=owner.headers
    )

    assert response.status_code == 204
    assert await count_transactions(portfolio) == 2


# A transaction id that doesn't exist: 404.
async def test_delete_missing_transaction_returns_404(client, owner, portfolio):
    response = await client.delete(
        "/api/transactions/999", params={"portfolio_id": portfolio["id"]}, headers=owner.headers
    )

    assert response.status_code == 404
    assert response.json()["detail"] == "Transaction not found"


# The transaction exists, but in another of your portfolios: 404, and it
# isn't deleted.
async def test_delete_with_wrong_portfolio_id_returns_404(client, owner, portfolio, add_tx, count_transactions):
    other = (await client.post("/api/portfolios", json={"name": "Other"}, headers=owner.headers)).json()
    purchase = await add_tx(portfolio, "AAPL", "BUY", 10, 100.0, "2026-01-05")

    response = await client.delete(
        f"/api/transactions/{purchase}", params={"portfolio_id": other["id"]}, headers=owner.headers
    )

    assert response.status_code == 404
    assert await count_transactions(portfolio) == 1


# portfolio_id is a required query parameter: 422 without it.
async def test_delete_without_portfolio_id_returns_422(client, owner, portfolio, add_tx):
    purchase = await add_tx(portfolio, "AAPL", "BUY", 10, 100.0, "2026-01-05")

    response = await client.delete(f"/api/transactions/{purchase}", headers=owner.headers)

    assert response.status_code == 422
