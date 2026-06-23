from typing import Annotated

from fastapi import FastAPI, APIRouter, Depends, HTTPException, status

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

import models
from database import get_db
from app.schemas import UserBase, UserCreate, UserResponse


router = APIRouter(prefix="/user", tags=["user"])


@router.post(
    response_model=UserResponse,
    status_code=status.HTTP_201_CREATED
)
async def create_user(user:UserCreate, db: Annotated[AsyncSession, Depends(get_db)]):
    result = await db.execute(
        select(models.User).where(models.User.username == user.username),
    )
    
    existing_user = result.scalars().first()
    
    if existing_user:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail='User already exists.'
        )
        
    result = await db.execute(
        select(models.User.email).where(models.User.email == user.email),
    )
    
    existing_email = result.scalars().first()
    
    if existing_email:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail='Email already registered.'
        )
    
    