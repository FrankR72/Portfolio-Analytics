from fastapi import APIRouter, Depends, HTTPException, status

from typing import Annotated

from pydantic import EmailStr

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db

from app import models

from app.schemas import LoginRequest

router = APIRouter()



# Validate email and log in.
@router.post(
    "",
    status_code=status.HTTP_200_OK
)
async def validate_email(credentials: LoginRequest, db: Annotated[AsyncSession, Depends(get_db)]):
    result = await db.execute(
        select(models.User).where(models.User.email == credentials.email)
    )
    
    db_user = result.scalars().first()
    
    if db_user is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Email NOT found in database."
        )
    return {
        "message": "Login successful.",
        "user_id": db_user.id,
        "username": db_user.username
    }