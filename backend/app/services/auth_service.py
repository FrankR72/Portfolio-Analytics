"""Log-in and resolution of the current user from a JWT.

Tokens are created and verified in security.py; this service looks up the
user they belong to. Every failure is reported as 401 with a
WWW-Authenticate: Bearer header.
"""

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
        """Check the credentials and return a new bearer token.

        The form's "username" field holds the user's email (matched
        case-insensitively). The JWT's "sub" claim is the user id, and the
        token expires after settings.access_token_expire_minutes.

        Raises:
            HTTPException: 401 if the email is unknown or the password is
                wrong (same message for both).
        """
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
        """Return the User that a bearer token belongs to.

        Used by routers.auth.get_current_user, the dependency of every
        protected route.

        Raises:
            HTTPException: 401 if the token is invalid or expired, its "sub"
                isn't an integer id, or the user no longer exists.
        """
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