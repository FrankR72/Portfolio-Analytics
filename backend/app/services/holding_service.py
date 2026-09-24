
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


    "Data Base retrieval of transactions"
    async def get_portfolio_transactions(self, portfolio_id: int , user_id: int):
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

    "Form current holdings dictionary based on all transactions"
    def build_holdings_dictionary(self, transactions: list[models.Transaction]):
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


    "Enrich holdings dictionary with data on current prices"
    async def enrich_holdings_with_current_prices(self, holdings: dict) -> dict:
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
        
        list_of_transactions = await self.get_portfolio_transactions(portfolio_id, user_id)
        holdings_dictionary = self.build_holdings_dictionary(list_of_transactions)
        # Remove holdings with zero shares before enriching with current prices
        holdings_dictionary = {symbol: data for symbol, data in holdings_dictionary.items() if data["number_current_shares"] > 0}
        enriched_holdings = await self.enrich_holdings_with_current_prices(holdings_dictionary)
        return [HoldingBase(**data) for data in enriched_holdings.values()]
