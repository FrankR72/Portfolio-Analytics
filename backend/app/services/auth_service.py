from fastapi import HTTPException, status
from fastapi.security import OAuth2PasswordRequestForm

from sqlalchemy import select, func

from schemas import Token

import models

from datetime import timedelta

from config import settings

from security import (
    verify_password,
    create_access_token,
    verify_access_token
)



class AuthService:  
    
    def __init__(self, session):
        self.db = session

    async def login_to_create_access_token(self, form_data: OAuth2PasswordRequestForm):
        """Login user and create access token"""
        # Note: OAuth2PasswordRequestForm uses "username" field, but we treat it as email
        result = await self.db.execute(
            select(models.User).where(
                func.lower(models.User.email) == form_data.username.lower()
            )
        )
        user = result.scalars().first()
        # Verify if user exists and if password is correct
        if not user or not verify_password(form_data.password, user.hashed_password):
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Incorrect email or password",
                headers={"WWW-Authenticate": "Bearer"},
            )
        access_token_expires = timedelta(minutes=settings.access_token_expire_minutes)
        access_token = create_access_token(
            data={
                "sub": str(user.id)
            },
            expires_delta=access_token_expires
        )
        return Token(access_token=access_token, token_type="bearer")
    
    
    async def get_current_user(self, token: str):
        """Get currently authenticated user"""
        user_id = verify_access_token(token)
        
        if user_id is None:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Invalid or expired token",
                headers={"WWW-Authenticate": "Bearer"}
            )
        # Validate user_id is a valid integer (defense against malformed JWT)
        try:
            user_id = int(user_id)
        except (TypeError, ValueError):
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Invalid or expired token",
                headers={"WWW-Authenticate": "Bearer"}
            )
        result = await self.db.execute(
            select(models.User).where(
                models.User.id == user_id
            )
        )
        user = result.scalars().first()
        if not user:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="User not found",
                headers={"WWW-Authenticate": "Bearer"},
            )
        return user