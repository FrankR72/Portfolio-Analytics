
from pwdlib import PasswordHash

from fastapi.security import OAuth2PasswordBearer

from datetime import UTC, datetime, timedelta

from config import settings

import jwt

password_hash = PasswordHash.recommended()

oauth2_scheme = OAuth2PasswordBearer(tokenUrl="api/users/token")

def hash_password(password: str) -> str:
    return password_hash.hash(password=password)

def verify_password(plain_password: str, hashed_password: str) -> bool:
    return password_hash.verify(password=plain_password, hash=hashed_password)

def create_access_token(data: dict, expires_delta: timedelta) -> str:
    """Create a JWT access token"""
    to_encode = data.copy()
    
    if expires_delta:
        expire = datetime.now(UTC) + expires_delta
    
    else:
        expire = datetime(UTC) + timedelta(minutes=settings.access_token_expire_minutes)
        
    to_encode.update({"exp": expire})
    
    encoded_jwt = jwt.encode(
        payload=to_encode,
        key=settings.secrety_key.get_secret_value(),
        algorithm=settings.algorithm
    )