from fastapi.security import OAuth2PasswordBearer

from datetime import timedelta, datetime, UTC

from config import settings

from pwdlib import PasswordHash

import jwt



password_hash = PasswordHash.recommended()
oauth2_scheme = OAuth2PasswordBearer(tokenUrl="/api/auth/token")

def hash_password(password: str) -> str:
    return password_hash.hash(password)

def verify_password(plain_password: str, hashed_password: str) -> bool:
    return password_hash.verify(plain_password, hashed_password)

def create_access_token(data: dict, expires_delta: timedelta) -> str:
    """Generate JWT aaccess token"""
    to_encode = data.copy()
    if expires_delta:
        expire = datetime.now(UTC) + expires_delta
        
    else:
        expire = datetime.now(UTC) + timedelta(minutes=settings.access_token_expire_minutes)
    
    to_encode.update({"exp": expire})
    encoded_jwt = jwt.encode(
        payload=to_encode,
        key=settings.secret_key.get_secret_value(),
        algorithm=settings.algorithm
    )
    return encoded_jwt

def verify_access_token(token: str) -> str | None:
    """Verify access token and respond with (user id) when valid"""
    try:
        payload = jwt.decode(
            jwt=token,
            key=settings.secret_key.get_secret_value(),
            algorithms=[settings.algorithm],
            options={"require": ["sub", "exp"]}
        )
    except jwt.InvalidTokenError:
        return None
    else:
        return payload.get("sub")