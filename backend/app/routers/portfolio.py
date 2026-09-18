from fastapi import APIRouter, Depends

from typing import Annotated

from sqlalchemy.ext.asyncio import AsyncSession

from database import get_db
from models import User
from schemas import PortfolioPrivate, PortfolioCreate

from services.portfolio_service import PortfolioService
from routers.auth import get_current_user


router = APIRouter()


def get_portfolio_service(db: Annotated[AsyncSession, Depends(get_db)]) -> PortfolioService:
    return PortfolioService(session=db)


"""This Endpoint is for returning a list of portfolios for a user."""
@router.get("", response_model=list[PortfolioPrivate])
async def list_portfolios_endpoint(
    service: Annotated[PortfolioService, Depends(get_portfolio_service)],
    user: Annotated[User, Depends(get_current_user)],
):
    return await service.list_portfolios(user.id)


"""This Endpoint is for creating a new portfolio."""
@router.post(
    "",
    response_model=PortfolioPrivate,
    status_code=201
)
async def create_portfolio_endpoint(
    service: Annotated[PortfolioService, Depends(get_portfolio_service)],
    user: Annotated[User, Depends(get_current_user)],
    portfolio: PortfolioCreate,
):
    return await service.create_portfolio(portfolio, user.id)