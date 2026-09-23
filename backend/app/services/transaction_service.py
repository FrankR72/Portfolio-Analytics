from fastapi import HTTPException, status

from sqlalchemy import select, func
from sqlalchemy.ext.asyncio import AsyncSession
from datetime import UTC, datetime, time

from schemas import ClosedTransaction, TransactionCreate

import models

import asyncio
from services.market_data_service import ticker_validation


class TransactionService():

    def __init__(self, session=AsyncSession):
        self.db = session

    """Register new transaction"""
    async def register_transaction(self, transaction: TransactionCreate, portfolio_id: int, user_id: int):

        result = await self.db.execute(
            select(models.Portfolio).where(
                models.Portfolio.id == portfolio_id,
                models.Portfolio.user_id == user_id
            )
        )
        portfolio_exists = result.scalars().first()
        if not portfolio_exists:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Portfolio not found"
            )

        transaction_datetime = (
        datetime.combine(transaction.transaction_date, time.min, tzinfo=UTC)
        if transaction.transaction_date is not None
        else datetime.now(UTC))

        symbol = transaction.symbol.strip().upper()
        # Add ticker validation
        recognized = await asyncio.to_thread(ticker_validation, symbol)
        if not recognized:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail=(
                    "Ticker not recognized. Verify the ticker exists "
                    "or try again later."
                ),
            )
            
        if transaction.transaction_type == models.TransactionType.SELL:
            await self._validate_sell(
                portfolio_id,
                symbol,
                transaction.quantity_actions,
                transaction_datetime,
            )

        new_transaction = models.Transaction(
            portfolio_id=portfolio_id,
            symbol=symbol,
            transaction_type=transaction.transaction_type,
            quantity_actions=transaction.quantity_actions,
            price=transaction.price,
            total_value=transaction.quantity_actions * transaction.price,
            transaction_date=transaction_datetime
        )

        self.db.add(new_transaction)
        await self.db.commit()
        await self.db.refresh(new_transaction)
        return new_transaction


    "Visualize all transactions for a portfolio"
    async def get_transactions(self, portfolio_id: int, user_id: int):
        portfolio_result = await self.db.execute(
            select(models.Portfolio.id).where(
                models.Portfolio.id == portfolio_id,
                models.Portfolio.user_id == user_id,
            )
        )
        if portfolio_result.scalar_one_or_none() is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Portfolio not found",
            )

        result = await self.db.execute(
            select(models.Transaction)
            .join(
                models.Portfolio,
                models.Transaction.portfolio_id == models.Portfolio.id
            )
            .where(
                models.Transaction.portfolio_id == portfolio_id,
                models.Portfolio.user_id == user_id
            )
            .order_by(models.Transaction.id)
            )
        ordered_transaction_list = result.scalars().all()

        return ordered_transaction_list

    async def get_closed_transactions(self, portfolio_id: int, user_id: int):
        portfolio_result = await self.db.execute(
            select(models.Portfolio.id).where(
                models.Portfolio.id == portfolio_id,
                models.Portfolio.user_id == user_id,
            )
        )
        if portfolio_result.scalar_one_or_none() is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Portfolio not found",
            )

        result = await self.db.execute(
            select(models.Transaction)
            .where(models.Transaction.portfolio_id == portfolio_id)
            .order_by(
                models.Transaction.transaction_date,
                models.Transaction.id,
            )
        )
        transactions = result.scalars().all()

        return self.build_closed_transactions(transactions)


    def build_closed_transactions(
        self,
        transactions: list[models.Transaction],
    ) -> list[ClosedTransaction]:
        holdings = {}
        closed_transactions = []

        for transaction in transactions:
            symbol = transaction.symbol
            if symbol not in holdings:
                holdings[symbol] = {
                    "number_current_shares": 0,
                    "cost_basis": 0.0,
                }

            holding = holdings[symbol]

            if transaction.transaction_type == models.TransactionType.BUY:
                holding["number_current_shares"] += transaction.quantity_actions
                holding["cost_basis"] += (
                    transaction.quantity_actions * transaction.price
                )
                continue

            if transaction.transaction_type == models.TransactionType.SELL:
                if holding["number_current_shares"] < transaction.quantity_actions:
                    raise HTTPException(
                        status_code=status.HTTP_400_BAD_REQUEST,
                        detail=f"Not enough shares to sell for {symbol}",
                    )

                avg_cost_per_share = (
                    holding["cost_basis"] / holding["number_current_shares"]
                )
                total_cost_of_shares_sold = (
                    avg_cost_per_share * transaction.quantity_actions
                )
                total_sold_price = transaction.price * transaction.quantity_actions
                realized_gain_loss = (
                    total_sold_price - total_cost_of_shares_sold
                )
                return_percentage = (
                    realized_gain_loss / total_cost_of_shares_sold * 100
                )

                closed_transactions.append(
                    ClosedTransaction(
                        transaction_date=transaction.transaction_date,
                        symbol=symbol,
                        number_shares_sold=transaction.quantity_actions,
                        avg_cost_per_share=avg_cost_per_share,
                        sold_price_per_share=transaction.price,
                        total_cost_of_shares_sold=total_cost_of_shares_sold,
                        total_sold_price=total_sold_price,
                        realized_gain_loss=realized_gain_loss,
                        return_percentage=return_percentage,
                    )
                )

                holding["number_current_shares"] -= transaction.quantity_actions
                holding["cost_basis"] -= total_cost_of_shares_sold
                if holding["number_current_shares"] == 0:
                    holding["cost_basis"] = 0.0

        return closed_transactions

    async def _validate_sell(
        self,
        portfolio_id: int,
        symbol: str,
        quantity: int,
        sale_at: datetime,
    ) -> None:
        result = await self.db.execute(
            select(models.Transaction).where(
                models.Transaction.portfolio_id == portfolio_id,
                models.Transaction.symbol == symbol,
            )
        )
        existing = result.scalars().all()
        def as_utc(value: datetime) -> datetime:
            # SQLite may return a datetime without timezone information.
            return (
                value.replace(tzinfo=UTC)
                if value.tzinfo is None
                else value.astimezone(UTC)
            )
        events = [
            (
                as_utc(item.transaction_date),
                item.id,
                item.quantity_actions
                if item.transaction_type == models.TransactionType.BUY
                else -item.quantity_actions,
            )
            for item in existing
        ]
        # A new transaction has no ID yet. Put it after existing transactions
        # if they have exactly the same timestamp.
        events.append((sale_at, float("inf"), -quantity))
        shares = 0
        for _, _, change in sorted(events):
            shares += change
            if shares < 0:
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail="Not enough shares to sell on that date",
                )
