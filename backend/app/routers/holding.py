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
    return HoldingService(session=db)

"""This endpoint is for getting the summary of holdings for a specific portfolio."""
@router.get("/{portfolio_id}", response_model=list[HoldingBase])
async def get_holdings_summary(
    service: Annotated[HoldingService, Depends(get_holding_service)],
    portfolio_id: int,
    user: Annotated[User, Depends(get_current_user)]
):
    return await service.summarize_holdings(portfolio_id, user_id=user.id)