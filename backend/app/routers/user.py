"""User routes, mounted at /api/users. Only sign-up for now.

Known issues (pending refactor):
    A duplicate username returns 406 instead of 409.
"""

from fastapi import APIRouter, Depends
from fastapi import status

from typing import Annotated

from sqlalchemy.ext.asyncio import AsyncSession

from database import get_db
from schemas import UserPrivate, UserCreate

from services.user_service import UserService



router = APIRouter()


def get_user_service(db: Annotated[AsyncSession, Depends(get_db)]) -> UserService:
    """Build a UserService on the request's database session."""
    return UserService(session=db)



@router.post(
    "",
    response_model=UserPrivate,
    status_code=status.HTTP_201_CREATED
)
async def create_user_endpoint(
    service: Annotated[UserService, Depends(get_user_service)],
    user: UserCreate
):
    """Sign up a new user. Public, no token needed.

    The password must be at least 8 characters; it is stored hashed.
    Returns 201 with the created user.

    Errors: 406 if the username is taken, 400 if the email is already
    registered (both case-insensitive), 422 if the body is invalid.
    """
    return await service.create_user(user)