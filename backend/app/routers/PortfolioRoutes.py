from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, status

from sqlalchemy import select
from sqlalchemy.orm import selectinload
from sqlalchemy.ext.asyncio import AsyncSession

from app import models

from app.database import get_db

from app.schemas import PortfolioBase, PortfolioCreate, PortfolioResponse, PortfolioUpdate


router = APIRouter()

# Select all portfolios in the db ---> ### Might have to delete or alter, don´t see the need for this. ###
@router.get("", response_model=list[PortfolioResponse])
async def get_portfolio(db: Annotated[AsyncSession, Depends(get_db)]):
    result = await db.execute(
        select(models.Portfolio)
        .options(selectinload(models.Portfolio.author))
        .order_by(models.Portfolio.date_created.desc())
    )
    
    portfolios = result.scalars().first()
    
    return portfolios

# Select one protfolio in the db by id
@router.get("/{portfolio_id}", response_model=PortfolioResponse)
async def get_one_portfolio(portfolio_id: int, db: Annotated[AsyncSession, Depends(get_db)]):
    result = await db.execute(
        select(models.Portfolio)
        .options(selectinload(models.Portfolio.author))
        .where(models.Portfolio.id == portfolio_id)
    )
    
    portfolio = result.scalars().first()
    
    if portfolio:
        return portfolio
    raise HTTPException(
        status_code=status.HTTP_404_NOT_FOUND,
        detail="Portfolio not found."
    )