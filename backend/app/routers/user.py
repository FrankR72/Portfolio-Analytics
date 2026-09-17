from fastapi import APIRouter, Depends
from fastapi import status

from typing import Annotated

from sqlalchemy.ext.asyncio import AsyncSession

from database import get_db
from schemas import UserPrivate, UserCreate

from services.user_service import UserService



router = APIRouter()


def get_user_service(db: Annotated[AsyncSession, Depends(get_db)]) -> UserService:
    return UserService(session=db)



"""This Endpoint is for creating a new user."""
@router.post(
    "",
    response_model=UserPrivate,
    status_code=status.HTTP_201_CREATED
)
async def create_user_endpoint(
    service: Annotated[UserService, Depends(get_user_service)],
    user: UserCreate
):
    return await service.create_user(user)