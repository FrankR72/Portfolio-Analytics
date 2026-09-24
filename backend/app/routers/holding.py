"""Holdings routes, mounted at /api/holdings. Requires a bearer token.

Known issues (pending refactor):
    The portfolio id is a path parameter here (/holdings/{id}) but a query
    parameter in /api/transactions; both could be nested under
    /api/portfolios/{id}/... with one shared ownership check.
"""

from fastapi import APIRouter, Depends

from typing import Annotated

from sqlalchemy.ext.asyncio import AsyncSession

from services.holding_service import HoldingService

from database import get_db

from schemas import HoldingBase

from models import User

from routers.auth import get_current_user

router = APIRouter()


def get_holding_service(db: Annotated[AsyncSession, Depends(get_db)]):
    """Build a HoldingService on the request's database session."""
    return HoldingService(session=db)

@router.get("/{portfolio_id}", response_model=list[HoldingBase])
async def get_holdings_summary(
    service: Annotated[HoldingService, Depends(get_holding_service)],
    portfolio_id: int,
    user: Annotated[User, Depends(get_current_user)]
):
    """List the open positions of a portfolio with live prices.

    One entry per symbol still held: shares, average cost, cost basis, and
    the current price, value, unrealized gain and return. The live fields are
    `null` for a symbol whose price lookup failed. Prices are fetched from
    Yahoo Finance on every call.

    Errors: 404 if the portfolio doesn't exist or isn't yours, 400 if its
    transaction history is invalid.
    """
    return await service.summarize_holdings(portfolio_id, user_id=user.id)