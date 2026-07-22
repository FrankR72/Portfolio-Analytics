from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, status
from fastapi.security import OAuth2PasswordRequestForm

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app import models

from app.database import get_db

from app.schemas import UserBase, UserCreate, UserUpdate, UserPublic, UserPrivate, Token

from datetime import timedelta

from auth import (
    oauth2_scheme,
    hash_password,
    verify_password,
    create_access_token,
    verify_access_token
)

from config import settings

router = APIRouter()

# ======== CREATE USER ========
@router.post(
    "",
    response_model=UserPrivate,
    status_code=status.HTTP_201_CREATED
)
async def create_user(user:UserCreate, db: Annotated[AsyncSession, Depends(get_db)]):
    
    # CHECK if the USER already EXISTS in the database.
    result = await db.execute(
        select(models.User).where(func.lower(models.User.username) == user.username.lower()),
    )
    
    existing_user = result.scalars().first()
    
    if existing_user:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail='User already exists.'
        )
        
    # CHECK if the EMAIL is already REGISTEDED in the database.
    result = await db.execute(
        select(models.User.email).where(func.lower(models.User.email) == user.email.lower()),
    )
    
    existing_email = result.scalars().first()
    
    if existing_email:
        raise HTTPException(
            status_code=status.HTTP_406_NOT_ACCEPTABLE,
            detail='Email already registered.'
        )
    
    # CREATE the new user.
    new_user = models.User(
        username = user.username,
        email = user.email,
        password_hash = hash_password(user.password)
    )    
    db.add(new_user)
    await db.commit()
    await db.refresh(new_user)
    return new_user

# ======== LOGIN TO ACCESS TOKEN ========
@router.post("/token", response_model=Token)
async def login_for_access_token(
    form_data: Annotated[OAuth2PasswordRequestForm, Depends()],
    db: Annotated[AsyncSession, Depends(get_db)]
):
    result = await db.execute(
        select(models.User).where(
            func.lower(models.User.username) == form_data.username.lower()
        )
    )

    user = result.scalars().first()
    
    if not user or not verify_password(form_data.password, user.hashed_password):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Incorrect Email or Password",
            headers={"WWW-Authenticate": "Bearer"}
        )
    
    access_token_expires = timedelta(minutes=settings.access_token_expire_minutes)
    access_token = create_access_token(
        data={"sub": str(user.id)},
        expires_delta=access_token_expires
    )
    return Token(access_token=access_token, token_type="bearer")


# ======== TOKEN VALIDATION ========
@router.get("/me", response_model=UserPrivate)
async def get_current_user(
    token: Annotated[str, Depends(oauth2_scheme)],
    db: Annotated[AsyncSession, Depends(get_db)]
):
    user_id = verify_access_token(token)
    
    if user_id is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid or expired token",
            headers={"WWW-Authenticate": "Bearer"},
        )
    
    try:
        user_id_int = int(user_id)
    except (TypeError, ValueError):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid or expired token",
            headers={"WWW-Authenticate": "Bearer"},
        )
        
    result = await db.execute(
        select(models.User).where(
            models.User.id == user_id_int
        )
    )
    
    user = result.scalars().first()
    
    if not user:
        raise HTTPException(
            detail="User not found",
            status_code=status.HTTP_401_UNAUTHORIZED,
            headers={"WWW-Authenticate": "Bearer"}
        )
    else: 
        return user
        


# ======== READ USER ========
@router.get("/{user_id}",response_model=UserPublic)
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
@router.patch("/{user_id}", response_model=UserPrivate) # UserPrivate is used when we expect only loged in user to get a response.
async def update_user(
    user_id: int, 
    user_update: UserUpdate,
    db: Annotated[AsyncSession, Depends(get_db)],
):
    
    result = await db.execute(
        select(models.User).where(models.User.id == user_id)
    )
    user = result.scalars().first()
    
    if not user:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST, 
            detail="User not found"
        )

    # Updated Username not None or not the same as the current one. 
    if user_update.username is not None and user_update.username.lower() != user.username.lower():
        username = await db.execute(
            select(models.User).where(func.lower(models.User.username) == user_update.username.lower())
        )
        
        existing_username = username.scalars().first()
        if existing_username:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Username already exists."
            )
            
    if user_update.email is not None and user_update.email.lower() != user.email.lower():
        result = await db.execute(
            select(models.User).where(func.lower(models.User.email) == user_update.email.lower())
        )
    
        existing_email = result.scalars().first()
        
        if existing_email:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Email already registered."
            )
    
    if user_update.username is not None:
        user.username = user_update.username
    if user_update.email is not None:
        user.email = user_update.email.lower()

    await db.commit()
    await db.refresh(user)
    return user



# ======== DELETE USER ========
@router.delete("/{user_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_user(
    user_id: int,
    db: Annotated[AsyncSession, Depends(get_db)]
):
    result = await db.execute(
        select(models.User).where(models.User.id == user_id)
    )
    
    user = result.scalars().first()
    
    if not user:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="User not found."
        )
    
    await db.delete(user)
    await db.commit()