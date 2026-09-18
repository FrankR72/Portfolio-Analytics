from fastapi import APIRouter, Depends

from sqlalchemy.ext.asyncio import AsyncSession


from services.transaction_service import TransactionService
from typing import Annotated

from database import get_db

from routers.auth import get_current_user

from models import User, Portfolio

from schemas import TransactionCreate, TransactionPrivate





router = APIRouter()


def get_transaction_service(db: Annotated[AsyncSession, Depends(get_db)]):
    return TransactionService(session=db)

"""This endpoint is for registering a transaction"""
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
    return await service.register_transaction(transaction, portfolio_id, user.id)


"""This endpoint is for getting all transactions of a portfolio"""
@router.get(
    "",
    response_model=list[TransactionPrivate]
)
async def get_transactions_endpoint(
    service: Annotated[TransactionService, Depends(get_transaction_service)],
    portfolio_id: int,
    user: Annotated[User, Depends(get_current_user)]
):
    return await service.get_transactions(portfolio_id, user.id)