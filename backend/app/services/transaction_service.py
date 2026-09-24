"""BUY/SELL transactions of a portfolio and the gains realized by sells.

Registers new transactions (checking the ticker against yfinance and
rejecting oversells), lists them, and computes realized gains per SELL with
position_accounting_service.

Known issues (pending refactor):
    - Creating a transaction returns 200 instead of 201.
    - The portfolio ownership check is re-implemented in every method.
"""

from fastapi import HTTPException, status

from sqlalchemy import select, func
from sqlalchemy.ext.asyncio import AsyncSession
from datetime import UTC, datetime, time

from schemas import ClosedTransaction, TransactionCreate

import models

import asyncio
from .market_data_service import ticker_validation

from .position_accounting_service import Position, apply_transaction



class TransactionService():

    def __init__(self, session:AsyncSession):
        self.db = session

    async def register_transaction(self, transaction: TransactionCreate, portfolio_id: int, user_id: int):
        """Validate and store a new BUY or SELL transaction.

        The symbol is stripped and uppercased. A given date is stored as
        midnight UTC of that day; without a date, the current time is used.
        total_value is computed as quantity * price.

        Returns:
            The stored models.Transaction.

        Raises:
            HTTPException: 404 if the portfolio isn't the user's, 422 if the
                ticker can't be priced on yfinance, 400 if a SELL exceeds
                the shares held on its date.
        """
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


    async def get_transactions(self, portfolio_id: int, user_id: int):
        """Return all transactions of a portfolio, ordered by id.

        The order is insertion order, not date order, so a backdated
        transaction appears after later-dated ones.

        Raises:
            HTTPException: 404 if the portfolio isn't the user's.
        """
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
        """Return the realized gain or loss of every SELL in a portfolio.

        Raises:
            HTTPException: 404 if the portfolio isn't the user's, 400 if its
                transaction history is invalid.
        """
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


    def build_closed_transactions(self, transactions: list[models.Transaction]):
        """Replay transactions and collect one ClosedTransaction per SELL.

        Args:
            transactions: Ordered by (transaction_date, id).

        Returns:
            list[ClosedTransaction] in replay order.

        Raises:
            HTTPException: 400 if the history is invalid, for example a sell
                of more shares than were held at that point.
        """
        positions = {}
        closed_transactions = []

        # Transactions must already be ordered by date, then ID.
        for transaction in transactions:
            position = positions.setdefault(transaction.symbol, Position())

            try:
                sale = apply_transaction(position, transaction)
            except ValueError as exc:
                raise HTTPException(status_code=400, detail=str(exc)) from exc

            if sale is not None:
                closed_transactions.append(ClosedTransaction(**sale))

        return closed_transactions

    async def _validate_sell(
        self,
        portfolio_id: int,
        symbol: str,
        quantity: int,
        sale_at: datetime,
    ) -> None:
        """Check that a new SELL never makes the share count negative.

        Replays the symbol's share count through time with the new sale
        inserted at sale_at. A backdated sell must be covered by shares held
        at its date, and must not leave a later existing sell uncovered.

        Raises:
            HTTPException: 400 if the share count drops below zero at any
                point.

        Known issues (pending refactor):
            - Uses its own replay instead of position_accounting_service.
            - Check-then-insert race: two sells submitted at the same moment
              can both pass the check.
        """
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
