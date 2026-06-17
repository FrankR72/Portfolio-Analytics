from typing import Annotated

from fastapi import FastAPI, APIRouter, Depends, HTTPException, status

from sqlalchemy.ext.asyncio import AsyncSession


import models
from database import get_db
from app.schemas import UserBase, UserCreate, UserResponse




router = APIRouter(prefix="/user", tags=["user"])


router.post("", response_model=UserResponse, status_code=status.HTTP_201_CREATED)
def create_user(user: UserCreate, db: Annotated[AsyncSession, Depends(get_db)]):
    pass