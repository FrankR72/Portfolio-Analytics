"""Portfolio routes, mounted at /api/portfolios. Requires a bearer token.

CRUD for the user's portfolios, plus the analytics used by the charts page
(allocation, unrealized gains and return over time).

Known issues (pending refactor):
    - A duplicate name returns 406 on create but 409 on rename.
    - /distribution and /unrealized_gains_distribution don't catch the
      ValueError that AnalyticService raises when a price lookup fails, so
      it becomes a 500.
"""

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
    """Build a PortfolioService on the request's database session."""
    return PortfolioService(session=db)

def get_analytic_service(db: Annotated[AsyncSession, Depends(get_db)]) -> AnalyticService:
    """Build an AnalyticService on the request's database session."""
    return AnalyticService(session=db)


@router.get("", response_model=list[PortfolioPrivate])
async def list_portfolios_endpoint(
    service: Annotated[PortfolioService, Depends(get_portfolio_service)],
    user: Annotated[User, Depends(get_current_user)],
):
    """List your portfolios, ordered by id."""
    return await service.list_portfolios(user.id)


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
    """Create a portfolio. Returns 201.

    Errors: 406 if you already have a portfolio with that name
    (case-insensitive).
    """
    return await service.create_portfolio(portfolio, user.id)


@router.put("/{portfolio_id}", response_model=PortfolioPrivate)
async def update_portfolio_endpoint(
    service: Annotated[PortfolioService, Depends(get_portfolio_service)],
    user: Annotated[User, Depends(get_current_user)],
    updates: PortfolioUpdate,
    portfolio_id: int,
):
    """Rename a portfolio.

    Errors: 404 if the portfolio doesn't exist or isn't yours, 409 if you
    already have another portfolio with that name (case-insensitive).
    """
    return await service.update_portfolio(portfolio_id, user.id, new_name=updates.name)


@router.delete("/{portfolio_id}", status_code=204)
async def delete_portfolio_endpoint(
    service: Annotated[PortfolioService, Depends(get_portfolio_service)],
    user: Annotated[User, Depends(get_current_user)],
    portfolio_id: int,
):
    """Delete a portfolio and all of its transactions. Returns 204.

    Errors: 404 if the portfolio doesn't exist or isn't yours.
    """
    await service.delete_portfolio(portfolio_id, user.id)

@router.get("/{portfolio_id}", response_model=PortfolioPrivate)
async def visualize_portfolio_endpoint(
    service: Annotated[PortfolioService, Depends(get_portfolio_service)],
    user: Annotated[User, Depends(get_current_user)],
    portfolio_id: int,
):
    """Get one portfolio (id, name, owner).

    Errors: 404 if the portfolio doesn't exist or isn't yours.
    """
    return await service.visualize_portfolio(portfolio_id, user.id)


@router.get("/{portfolio_id}/distribution")
async def get_portfolio_distribution_endpoint(
    service: Annotated[AnalyticService, Depends(get_analytic_service)],
    user: Annotated[User, Depends(get_current_user)],
    portfolio_id: int,
):
    """Market value of each open position and its share of the total.

    Returns `{total_value, distribution: {SYMBOL: {current_value,
    distribution_percentage}}}`, using live prices from Yahoo Finance.

    Errors: 404 if the portfolio doesn't exist or isn't yours, 400 if its
    transaction history is invalid, 500 if a price lookup fails (known
    issue).
    """
    total_value, distribution = await service.get_portfolio_distribution(user.id, portfolio_id)
    return {"total_value": total_value, "distribution": distribution}


@router.get("/{portfolio_id}/unrealized_gains_distribution")
async def get_portfolio_unrealized_gains_distribution_endpoint(
    service: Annotated[AnalyticService, Depends(get_analytic_service)],
    user: Annotated[User, Depends(get_current_user)],
    portfolio_id: int,
):
    """Unrealized gain or loss of each open position.

    Returns `{unrealized_gains_distribution: {SYMBOL: {unrealized_gain_loss}}}`,
    computed as current market value minus cost basis.

    Errors: 404 if the portfolio doesn't exist or isn't yours, 400 if its
    transaction history is invalid, 500 if a price lookup fails (known
    issue).
    """
    distribution = await service.get_portfolio_unrealized_gains_distribution(user.id, portfolio_id)
    return {"unrealized_gains_distribution": distribution}


@router.get("/{portfolio_id}/performance")
async def get_portfolio_performance_endpoint(
    portfolio_id: int,
    start_date: date,
    end_date: date,
    service: Annotated[AnalyticService, Depends(get_analytic_service)],
    user: Annotated[User, Depends(get_current_user)],
):
    """Daily cumulative return of a portfolio between two dates.

    `start_date` and `end_date` are required query parameters (YYYY-MM-DD),
    with `end_date` no later than today. Returns an approximate time-weighted
    return: buys and sells don't count as gains. See
    AnalyticService.get_portfolio_performance for the method and every
    response key.

    Errors: 404 if the portfolio doesn't exist or isn't yours, 422 if the
    dates are invalid or the return can't be computed for the period (for
    example a stock split in the window, or missing prices).
    """
    # AnalyticService raises ValueError instead of HTTPException.
    try:
        return await service.get_portfolio_performance(
            user_id=user.id,
            portfolio_id=portfolio_id,
            start_date=start_date,
            end_date=end_date,
        )
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc