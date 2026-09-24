"""Open positions of a portfolio, valued at current market prices.

Loads a portfolio's transactions, replays them with
position_accounting_service to get shares and cost basis per symbol, and
adds live prices from market_data_service. AnalyticService reuses the
loading and replay steps.

Known issues (pending refactor):
    The portfolio ownership check is re-implemented here instead of being
    a shared dependency.
"""

from fastapi import HTTPException, status

import asyncio

from sqlalchemy.ext.asyncio import AsyncSession

import models

from sqlalchemy import select, func

from services.market_data_service import get_current_stock_price

from schemas import HoldingBase

from .position_accounting_service import Position, apply_transaction


class HoldingService:
    def __init__(self, session: AsyncSession):
        self.db = session


    async def get_portfolio_transactions(self, portfolio_id: int , user_id: int):
        """Load all transactions of a portfolio owned by the user.

        Returns:
            Transactions ordered by (transaction_date, id), the order that
            build_holdings_dictionary and apply_transaction require.

        Raises:
            HTTPException: 404 if the portfolio doesn't exist or belongs to
                another user.
        """
        ownership = await self.db.execute(
            select(models.Portfolio)
            .where(models.Portfolio.id == portfolio_id,
                   models.Portfolio.user_id == user_id)
        )
        if not ownership.scalar():
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Portfolio not found"
            )

        result = await self.db.execute(
            select(models.Transaction)
            .join(models.Portfolio,
                  models.Portfolio.id == models.Transaction.portfolio_id)
            .where(models.Portfolio.id == portfolio_id,
                   models.Portfolio.user_id == user_id)
            .order_by(models.Transaction.transaction_date,
                      models.Transaction.id)
        )
        list_of_transactions = result.scalars().all()
        return list_of_transactions

    def build_holdings_dictionary(self, transactions: list[models.Transaction]):
        """Replay transactions into one entry per symbol ever traded.

        Args:
            transactions: Ordered by (transaction_date, id).

        Returns:
            {symbol: {"symbol", "number_current_shares",
            "avg_cost_per_share", "cost_bases"}}. Symbols that were fully
            sold are included with 0 shares; callers filter them out.

        Raises:
            HTTPException: 400 if the history is invalid, for example a sell
                of more shares than were held at that point.
        """
        positions = {}

        # Transactions must already be ordered by date, then ID.
        for transaction in transactions:
            position = positions.setdefault(transaction.symbol, Position())

            try:
                apply_transaction(position, transaction)
            except ValueError as exc:
                raise HTTPException(status_code=400, detail=str(exc)) from exc

        return {
            symbol: {
                "symbol": symbol,
                "number_current_shares": position.shares,
                "avg_cost_per_share": position.average_cost,
                "cost_bases": position.cost_basis,
            }
            for symbol, position in positions.items()
        }


    async def enrich_holdings_with_current_prices(self, holdings: dict) -> dict:
        """Add current price, value and unrealized gain to each holding.

        Modifies the given dict in place and also returns it. Adds
        "current_price_per_share", "current_value", "unrealized_gain_loss"
        and "return_percentage". If a price lookup fails, those fields are
        set to None for that symbol instead of failing the whole request.
        Symbols with 0 shares are skipped and get no new fields.

        Fetches one symbol at a time from yfinance.
        """
        for symbol, data in holdings.items():
            if data["number_current_shares"] == 0:
                continue
            try:
                current_price = await asyncio.to_thread(get_current_stock_price, symbol)
            except ValueError:
                data["current_price_per_share"] = None
                data["current_value"] = None
                data["unrealized_gain_loss"] = None
                data["return_percentage"] = None
                continue
            data["current_price_per_share"] = current_price
            data["current_value"] = current_price * data["number_current_shares"]
            data["unrealized_gain_loss"] = data["current_value"] - data["cost_bases"]
            data["return_percentage"] = (data["unrealized_gain_loss"] / data["cost_bases"]) * 100 if data["cost_bases"] != 0 else 0
        return holdings


    async def summarize_holdings(
        self,
        portfolio_id: int,
        user_id: int
    ) -> list[HoldingBase]:
        """Return the open positions of a portfolio with live prices.

        Backs GET /api/holdings/{portfolio_id}. Fully sold symbols are
        left out.

        Raises:
            HTTPException: 404 if the portfolio isn't the user's, 400 if its
                transaction history is invalid.
        """
        list_of_transactions = await self.get_portfolio_transactions(portfolio_id, user_id)
        holdings_dictionary = self.build_holdings_dictionary(list_of_transactions)
        # Remove holdings with zero shares before enriching with current prices
        holdings_dictionary = {symbol: data for symbol, data in holdings_dictionary.items() if data["number_current_shares"] > 0}
        enriched_holdings = await self.enrich_holdings_with_current_prices(holdings_dictionary)
        return [HoldingBase(**data) for data in enriched_holdings.values()]
