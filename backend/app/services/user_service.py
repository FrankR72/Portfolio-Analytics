"""User sign-up.

Known issues (pending refactor):
    - A duplicate username returns 406 instead of 409.
    - Username and email uniqueness is checked case-insensitively in Python,
      but the database constraint is case-sensitive, so two requests at the
      same moment can create duplicates.
"""

from fastapi import HTTPException, status

from sqlalchemy import select, func
from sqlalchemy.ext.asyncio import AsyncSession

from schemas import UserCreate

import models

from security import hash_password


class UserService:
    
    def __init__(self, session: AsyncSession):
        self.db = session

    async def create_user(self, user: UserCreate):
        """Register a new user with a hashed password.

        The email is stored lowercased; the username keeps its original
        case.

        Raises:
            HTTPException: 406 if the username is taken, 400 if the email is
                already registered (both compared case-insensitively).
        """
        result = await self.db.execute(
            select(models.User).where(
                func.lower(models.User.username) == user.username.lower()
            )
        )
        user_exists = result.scalars().first()
        if user_exists:
            raise HTTPException(
                status_code=status.HTTP_406_NOT_ACCEPTABLE,
                detail="Username already exists"
            ) 
        result = await self.db.execute(
            select(models.User).where(
                func.lower(models.User.email) == user.email.lower()
            )
        )
        email_registered = result.scalars().first()
        if email_registered:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Email already registered"
            )   
        new_user = models.User(
            username=user.username,
            email=user.email.lower(),
            hashed_password=hash_password(user.password)
        )
        self.db.add(new_user)
        await self.db.commit()
        await self.db.refresh(new_user)
        return new_user