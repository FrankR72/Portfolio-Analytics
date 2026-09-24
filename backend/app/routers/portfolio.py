from fastapi import APIRouter, Depends

from typing import Annotated

from sqlalchemy.ext.asyncio import AsyncSession

from database import get_db
from models import User
from schemas import PortfolioPrivate, PortfolioCreate, PortfolioUpdate

from services.portfolio_service import PortfolioService
from routers.auth import get_current_user

from services.analytic_service import AnalyticService

from datetime import date
from fastapi import HTTPException


router = APIRouter()


def get_portfolio_service(db: Annotated[AsyncSession, Depends(get_db)]) -> PortfolioService:
    return PortfolioService(session=db)

def get_analytic_service(db: Annotated[AsyncSession, Depends(get_db)]) -> AnalyticService:
    return AnalyticService(session=db)


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


"""This Endpoint is for updating a portfolio."""
@router.put("/{portfolio_id}", response_model=PortfolioPrivate)
async def update_portfolio_endpoint(
    service: Annotated[PortfolioService, Depends(get_portfolio_service)],
    user: Annotated[User, Depends(get_current_user)],
    updates: PortfolioUpdate,
    portfolio_id: int,
):
    return await service.update_portfolio(portfolio_id, user.id, new_name=updates.name)


"""This Endpoint is for deleting a portfolio."""
@router.delete("/{portfolio_id}", status_code=204)
async def delete_portfolio_endpoint(
    service: Annotated[PortfolioService, Depends(get_portfolio_service)],
    user: Annotated[User, Depends(get_current_user)],
    portfolio_id: int,
):
    await service.delete_portfolio(portfolio_id, user.id)

"""This Endpoint is for visualizing a portfolio."""
@router.get("/{portfolio_id}", response_model=PortfolioPrivate)
async def visualize_portfolio_endpoint(
    service: Annotated[PortfolioService, Depends(get_portfolio_service)],
    user: Annotated[User, Depends(get_current_user)],
    portfolio_id: int,
):
    return await service.visualize_portfolio(portfolio_id, user.id)


"""This Endpoint is for getting the distribution of a portfolio."""
@router.get("/{portfolio_id}/distribution")
async def get_portfolio_distribution_endpoint(
    service: Annotated[AnalyticService, Depends(get_analytic_service)],
    user: Annotated[User, Depends(get_current_user)],
    portfolio_id: int,
):
    total_value, distribution = await service.get_portfolio_distribution(user.id, portfolio_id)
    return {"total_value": total_value, "distribution": distribution}


"""This Endpoint is for getting the unrealized gains distribution of a portfolio."""
@router.get("/{portfolio_id}/unrealized_gains_distribution")
async def get_portfolio_unrealized_gains_distribution_endpoint(
    service: Annotated[AnalyticService, Depends(get_analytic_service)],
    user: Annotated[User, Depends(get_current_user)],
    portfolio_id: int,
):
    distribution = await service.get_portfolio_unrealized_gains_distribution(user.id, portfolio_id)
    return {"unrealized_gains_distribution": distribution}


"""This Endpoint is for getting the performance of a portfolio over a specified date range."""
@router.get("/{portfolio_id}/performance")
async def get_portfolio_performance_endpoint(
    portfolio_id: int,
    start_date: date,
    end_date: date,
    service: Annotated[AnalyticService, Depends(get_analytic_service)],
    user: Annotated[User, Depends(get_current_user)],
):
    try:
        return await service.get_portfolio_performance(
            user_id=user.id,
            portfolio_id=portfolio_id,
            start_date=start_date,
            end_date=end_date,
        )
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc