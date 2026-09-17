from fastapi import APIRouter, Depends
from fastapi.security import OAuth2PasswordRequestForm

from typing import Annotated

from sqlalchemy.ext.asyncio import AsyncSession

from database import get_db
from schemas import Token, UserPrivate

from services.auth_service import AuthService

from security import oauth2_scheme


router = APIRouter()


def get_auth_service(db: Annotated[AsyncSession, Depends(get_db)]) -> AuthService:
    return AuthService(session=db)



"""This Endpoint is for login in and creating an JWT access token."""
@router.post(
    "/token",
    response_model=Token
)
async def login_to_create_access_token_endpoint(
    service: Annotated[AuthService, Depends(get_auth_service)],
    form_data: Annotated[OAuth2PasswordRequestForm, Depends()]
):
    return await service.login_to_create_access_token(form_data)


"""This Endpoint is for getting the current JWT token."""
@router.get(
    "/me",
    response_model=UserPrivate
)
async def get_current_user_based_on_token(
    service: Annotated[AuthService, Depends(get_auth_service)],
    token: Annotated[str, Depends(oauth2_scheme)]
):
    return await service.get_current_user(token)