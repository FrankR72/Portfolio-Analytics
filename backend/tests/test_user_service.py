
from fastapi import Depends

from sqlalchemy.ext.asyncio import AsyncSession

from typing import Annotated

from app.services.user_service import UserService

from app.database import get_db

import pytest


def get_user_service(db: Annotated[AsyncSession, Depends(get_db)]) -> UserService:
    return UserService(session=db)


def test_function(
    service: Annotated[UserService, Depends(get_user_service)]
):
    pass