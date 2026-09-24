"""Transaction routes, mounted at /api/transactions. Requires a bearer token.

Every route takes the portfolio as the `portfolio_id` query parameter.

Known issues (pending refactor):
    - Registering a transaction returns 200 instead of 201.
    - The portfolio id is a query parameter here but a path parameter in
      /api/holdings/{id}.
"""

from fastapi import APIRouter, Depends

from sqlalchemy.ext.asyncio import AsyncSession


from services.transaction_service import TransactionService
from typing import Annotated

from database import get_db

from routers.auth import get_current_user

from models import User

from schemas import ClosedTransaction, TransactionCreate, TransactionPrivate





router = APIRouter()


def get_transaction_service(db: Annotated[AsyncSession, Depends(get_db)]):
    """Build a TransactionService on the request's database session."""
    return TransactionService(session=db)

@router.post(
    "",
    response_model=TransactionPrivate
)
async def register_transaction_endpoint(
    service: Annotated[TransactionService, Depends(get_transaction_service)],
    transaction: TransactionCreate,
    portfolio_id: int,
    user: Annotated[User, Depends(get_current_user)]
):
    """Record a BUY or SELL in a portfolio.

    The ticker is uppercased and must have a price on Yahoo Finance. The
    date is optional (defaults to now) and can be in the past; a backdated
    SELL is checked against the shares held on that date.

    Errors: 404 if the portfolio doesn't exist or isn't yours, 422 if the
    ticker isn't recognized (or Yahoo Finance is unreachable), 400 if a SELL
    exceeds the shares held.
    """
    return await service.register_transaction(transaction, portfolio_id, user.id)


@router.get(
    "",
    response_model=list[TransactionPrivate]
)
async def get_transactions_endpoint(
    service: Annotated[TransactionService, Depends(get_transaction_service)],
    portfolio_id: int,
    user: Annotated[User, Depends(get_current_user)]
):
    """List every transaction of a portfolio, ordered by id (insertion
    order, not date).

    Errors: 404 if the portfolio doesn't exist or isn't yours.
    """
    return await service.get_transactions(portfolio_id, user.id)

@router.get("/closed", response_model=list[ClosedTransaction])
async def get_closed_transactions_endpoint(
    service: Annotated[TransactionService, Depends(get_transaction_service)],
    portfolio_id: int,
    user: Annotated[User, Depends(get_current_user)]
):
    """List the realized gain or loss of every SELL in a portfolio.

    Uses the average cost method: each sale is matched against the average
    cost of the shares held just before it.

    Errors: 404 if the portfolio doesn't exist or isn't yours, 400 if its
    transaction history is invalid.
    """
    return await service.get_closed_transactions(portfolio_id, user.id)
