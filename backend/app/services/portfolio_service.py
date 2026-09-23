from fastapi import HTTPException, status

from sqlalchemy import select, func
from sqlalchemy.ext.asyncio import AsyncSession

from schemas import PortfolioCreate

import models

# Create Portfolio

class PortfolioService():
    
    def __init__(self, session: AsyncSession):
        self.db = session

    """Create new portfolio"""
    async def create_portfolio(self, portfolio: PortfolioCreate, user_id: int):
        
        result = await self.db.execute(
            select(models.Portfolio)
                .where(
                    models.Portfolio.user_id == user_id,
                    func.lower(models.Portfolio.name) == portfolio.name.lower()
                )
        )
        portfolio_exists = result.scalars().first()
        if portfolio_exists:
            raise HTTPException(
                status_code=status.HTTP_406_NOT_ACCEPTABLE,
                detail="Portfolio name already exists"
            )
        
    
        new_portfolio = models.Portfolio(
            name=portfolio.name,
            user_id=user_id
        )
        self.db.add(new_portfolio)
        await self.db.commit()
        await self.db.refresh(new_portfolio)
        return new_portfolio

    
    """Get list of portfolios for a user"""
    async def list_portfolios(self, user_id: int):
        result = await self.db.execute(
            select(models.Portfolio)
            .where(models.Portfolio.user_id == user_id)
            .order_by(models.Portfolio.id)
        )
        
        portfolios_list = result.scalars().all()
        
        return portfolios_list
    
    
    """Visualize a portfolio"""
    async def visualize_portfolio(self, portfolio_id: int, user_id: int):
        result = await self.db.execute(
            select(models.Portfolio)
            .where(
                models.Portfolio.id == portfolio_id,
                models.Portfolio.user_id == user_id
            )
        )
        existing_portfolio = result.scalars().first()
        if existing_portfolio is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Portfolio not found"
            )
        return existing_portfolio