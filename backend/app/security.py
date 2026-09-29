"""Password hashing and JWT access tokens.

Low-level helpers used by UserService (hashing on sign-up) and AuthService
(login and resolving the current user). This module knows nothing about the
database or HTTP errors: callers turn a False/None result into a 401.

Also defines oauth2_scheme, the dependency that reads the
"Authorization: Bearer <token>" header for routers.auth.get_current_user.

Known issues (pending refactor):
    - create_access_token types expires_delta as required, yet falls back to
      the configured expiry when it is falsy. The only caller always passes
      the same configured value, so the fallback never runs.
"""

from fastapi.security import OAuth2PasswordBearer

from datetime import timedelta, datetime, UTC

from core.config import settings

from pwdlib import PasswordHash

import jwt



# pwdlib's recommended hasher is argon2. The hash string stores the algorithm,
# salt and parameters, so verify() needs nothing else.
password_hash = PasswordHash.recommended()
# tokenUrl only tells /docs where the "Authorize" button logs in; the
# dependency itself just extracts the bearer token (401 if it's missing).
oauth2_scheme = OAuth2PasswordBearer(tokenUrl="/api/auth/token")

def hash_password(password: str) -> str:
    """Hash a plain-text password for storage in User.hashed_password."""
    return password_hash.hash(password)


def verify_password(plain_password: str, hashed_password: str) -> bool:
    """Return True if plain_password matches the stored hash."""
    return password_hash.verify(plain_password, hashed_password)


def create_access_token(data: dict, expires_delta: timedelta) -> str:
    """Create a signed JWT carrying data plus an "exp" claim.

    Args:
        data: Claims to encode. AuthService passes {"sub": str(user.id)};
            "sub" must be a string for verify_access_token to accept it.
        expires_delta: Token lifetime from now. If falsy, falls back to
            settings.access_token_expire_minutes.

    Returns:
        The encoded token, signed with settings.secret_key and
        settings.algorithm.
    """
    # Copy so the caller's dict doesn't get the "exp" claim added to it.
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
    """Return the token's "sub" claim (the user id as a string) if valid.

    Returns None instead of raising when the signature is wrong, the token is
    expired or malformed, or "sub"/"exp" is missing. The caller converts the
    id to int and raises the 401.
    """
    try:
        payload = jwt.decode(
            jwt=token,
            key=settings.secret_key.get_secret_value(),
            # Pin the accepted algorithm so a token can't choose its own
            # (for example "none").
            algorithms=[settings.algorithm],
            options={"require": ["sub", "exp"]}
        )
    except jwt.InvalidTokenError:
        return None
    else:
        return payload.get("sub")
