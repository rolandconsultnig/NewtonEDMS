"""Authentication helpers: password hashing, JWT, current-user dependencies.

Tokens are issued as HttpOnly cookies for browser sessions, while still being
accepted via the ``Authorization: Bearer`` header for API/OpenAPI clients. Each
token carries a ``jti``; logging out stores it in ``revoked_tokens`` so it stops
being honoured before its natural expiry.
"""
import uuid
from datetime import timedelta
from typing import Optional

from fastapi import Depends, HTTPException, Request, status
from fastapi.security import OAuth2PasswordBearer
from jose import JWTError, jwt
from passlib.context import CryptContext
from sqlalchemy.orm import Session

from app.config import settings
from app.database import get_db, now
from app.models import RevokedToken, User

pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")
# auto_error=False so we can fall back to the auth cookie before raising.
oauth2_scheme = OAuth2PasswordBearer(tokenUrl="/api/auth/login", auto_error=False)


def verify_password(plain: str, hashed: str) -> bool:
    return pwd_context.verify(plain, hashed)


def get_password_hash(password: str) -> str:
    return pwd_context.hash(password)


def validate_password_strength(password: str) -> None:
    """Enforce the minimum password policy; raises 400 on violation."""
    if len(password) < settings.password_min_length:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Password must be at least {settings.password_min_length} characters long",
        )
    if not any(c.isalpha() for c in password) or not any(c.isdigit() for c in password):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Password must contain at least one letter and one digit",
        )


def create_access_token(data: dict, expires: Optional[timedelta] = None) -> str:
    to_encode = data.copy()
    expire = now() + (expires or timedelta(minutes=settings.access_token_expire_minutes))
    to_encode.update({"exp": expire, "jti": uuid.uuid4().hex})
    return jwt.encode(to_encode, settings.secret_key, algorithm=settings.algorithm)


def get_token(
    request: Request,
    token: Optional[str] = Depends(oauth2_scheme),
) -> str:
    """Resolve the bearer token from the Authorization header, then the auth cookie."""
    if token:
        return token
    cookie_token = request.cookies.get(settings.cookie_name)
    if cookie_token:
        return cookie_token
    raise HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="Not authenticated",
        headers={"WWW-Authenticate": "Bearer"},
    )


def get_current_user(token: str = Depends(get_token), db: Session = Depends(get_db)) -> User:
    credentials_exception = HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="Could not validate credentials",
        headers={"WWW-Authenticate": "Bearer"},
    )
    try:
        payload = jwt.decode(token, settings.secret_key, algorithms=[settings.algorithm])
        username = payload.get("sub")
        jti = payload.get("jti")
        if username is None or jti is None:
            raise credentials_exception
    except JWTError:
        raise credentials_exception
    # Reject tokens that have been revoked (e.g. via /api/auth/logout).
    if db.query(RevokedToken).filter(RevokedToken.jti == jti).first():
        raise credentials_exception
    user = db.query(User).filter(User.username == username).first()
    if user is None or not user.is_active:
        raise credentials_exception
    return user


def require_role(*roles: str):
    def _check(user: User = Depends(get_current_user)) -> User:
        if user.role not in roles:
            raise HTTPException(status_code=403, detail="Insufficient privileges")
        return user

    return _check


def decode_token(token: str) -> dict:
    """Best-effort decode of a token; returns ``{}`` if invalid/expired."""
    try:
        return jwt.decode(token, settings.secret_key, algorithms=[settings.algorithm])
    except JWTError:
        return {}
