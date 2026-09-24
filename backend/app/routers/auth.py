"""Authentication routes, mounted at /api/auth.

Also defines get_current_user, the dependency that every protected route in
the other routers imports to resolve the bearer token into a User.
"""

from fastapi import APIRouter, Depends
from fastapi.security import OAuth2PasswordRequestForm

from typing import Annotated

from sqlalchemy.ext.asyncio import AsyncSession

from database import get_db
from models import User
from schemas import Token, UserPrivate

from services.auth_service import AuthService

from security import oauth2_scheme


router = APIRouter()


def get_auth_service(db: Annotated[AsyncSession, Depends(get_db)]) -> AuthService:
    """Build an AuthService on the request's database session."""
    return AuthService(session=db)


async def get_current_user(
    service: Annotated[AuthService, Depends(get_auth_service)],
    token: Annotated[str, Depends(oauth2_scheme)],
) -> User:
    """Dependency for protected routes: return the User owning the token.

    Reads the "Authorization: Bearer <token>" header through oauth2_scheme.
    Raises 401 if the header is missing, or the token is invalid, expired or
    belongs to a user that no longer exists.
    """
    return await service.get_current_user(token)


@router.post(
    "/token",
    response_model=Token
)
async def login_to_create_access_token_endpoint(
    service: Annotated[AuthService, Depends(get_auth_service)],
    form_data: Annotated[OAuth2PasswordRequestForm, Depends()]
):
    """Log in and get a JWT access token.

    Takes an OAuth2 form (not JSON). The `username` field must contain the
    user's **email**. Returns `{access_token, token_type: "bearer"}`; the
    token expires after 30 minutes by default and there is no refresh.

    Errors: 401 if the email or password is wrong.
    """
    return await service.login_to_create_access_token(form_data)


@router.get(
    "/me",
    response_model=UserPrivate
)
async def get_current_user_based_on_token(
    user: Annotated[User, Depends(get_current_user)],
):
    """Return the user that the bearer token belongs to.

    The frontend calls it to check that a stored token is still valid.

    Errors: 401 if the token is missing, invalid or expired.
    """
    return user
