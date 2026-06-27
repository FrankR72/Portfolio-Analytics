from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, status

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

import models
from database import get_db
from app.schemas import UserBase, UserCreate, UserResponse


router = APIRouter(prefix="/user", tags=["user"])

# ======== CREATE USER ========
@router.post(
    response_model=UserResponse,
    status_code=status.HTTP_201_CREATED
)
async def create_user(user:UserCreate, db: Annotated[AsyncSession, Depends(get_db)]):
    
    # CHECK if the USER already EXISTS in the database.
    result = await db.execute(
        select(models.User).where(models.User.username == user.username),
    )
    
    existing_user = result.scalars().first()
    
    if existing_user:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail='User already exists.'
        )
        
    # CHECK if the EMAIL is already REGISTEDED in the database.
    result = await db.execute(
        select(models.User.email).where(models.User.email == user.email),
    )
    
    existing_email = result.scalars().first()
    
    if existing_email:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail='Email already registered.'
        )
    
    # CREATE the new user.
    new_user = models.User(
        username = user.username,
        email = user.email
    )    
    db.add(new_user)
    await db.commit()
    await db.refresh(new_user)
    return new_user


# ======== READ USER ========
@router.get("/{user_id}",response_model=UserResponse,)
async def get_user(user_id: int, db: Annotated[AsyncSession, Depends(get_db)]):
    
    # RETRIEVE user from the database based on id. 
    result = await db.execute(
        select(models.User).where(models.User.id == user_id)
    )
    
    user = result.scalars().first()
    
    if user:
        return user
    
    raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="User not found.")
    
    


# ======== UPDATE USER ========
@router.patch("")
async def update_user():
    pass


# ======== DELETE USER ========
@router.delete()
async def delete_user():
    pass