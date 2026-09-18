from fastapi import HTTPException, status

from sqlalchemy import select, func
from sqlalchemy.ext.asyncio import AsyncSession
from datetime import UTC, datetime, time

from schemas import TransactionCreate, PortfolioPrivate

import models


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
            
        new_transaction = models.Transaction(
            portfolio_id=portfolio_id,
            symbol=transaction.symbol,
            transaction_type=transaction.transaction_type,
            quantity_actions=transaction.quantity_actions,
            price=transaction.price,
        )
        if transaction.transaction_date is not None:
            new_transaction.transaction_date = datetime.combine(
                transaction.transaction_date, time.min, tzinfo=UTC
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
