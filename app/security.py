"""Authentication helpers: password hashing, JWT, current-user dependencies.

Tokens are issued as HttpOnly cookies for browser sessions, while still being
accepted via the ``Authorization: Bearer`` header for API/OpenAPI clients. Each
token carries a ``jti``; logging out stores it in ``revoked_tokens`` so it stops
being honoured before its natural expiry.
"""
import uuid
from datetime import timedelta

import bcrypt
from fastapi import Depends, HTTPException, Request, status
from fastapi.security import OAuth2PasswordBearer
from jose import JWTError, jwt
from sqlalchemy.orm import Session

from app.config import settings
from app.database import get_db, now
from app.models import ApiKey, RevokedToken, User
from app.presence import presence_manager

# auto_error=False so we can fall back to the auth cookie before raising.
oauth2_scheme = OAuth2PasswordBearer(tokenUrl="/api/auth/login", auto_error=False)


def verify_password(plain: str, hashed: str) -> bool:
    if not plain or not hashed:
        return False
    try:
        return bcrypt.checkpw(plain.encode("utf-8")[:72], hashed.encode("utf-8"))
    except Exception:
        return False


def get_password_hash(password: str) -> str:
    pwd_bytes = password.encode("utf-8")[:72]
    salt = bcrypt.gensalt()
    return bcrypt.hashpw(pwd_bytes, salt).decode("utf-8")


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


def create_access_token(data: dict, expires: timedelta | None = None) -> str:
    to_encode = data.copy()
    expire = now() + (expires or timedelta(minutes=settings.access_token_expire_minutes))
    to_encode.update({"exp": expire, "jti": uuid.uuid4().hex})
    return jwt.encode(to_encode, settings.secret_key, algorithm=settings.algorithm)


def get_token(
    request: Request,
    token: str | None = Depends(oauth2_scheme),
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


def _user_from_jwt(token: str, db: Session) -> User | None:
    try:
        payload = jwt.decode(token, settings.secret_key, algorithms=[settings.algorithm])
        username = payload.get("sub")
        jti = payload.get("jti")
        if username is None or jti is None:
            return None
    except JWTError:
        return None
    if db.query(RevokedToken).filter(RevokedToken.jti == jti).first():
        return None
    user = db.query(User).filter(User.username == username).first()
    if user is None or not user.is_active:
        return None
    return user


def _user_from_api_key(raw: str, db: Session) -> User | None:
    if not raw or len(raw) < 8:
        return None
    prefix = raw[:8]
    for key in db.query(ApiKey).filter(ApiKey.prefix == prefix).all():
        if verify_password(raw, key.key_hash):
            key.last_used_at = now()
            db.commit()
            user = db.get(User, key.user_id)
            if user and user.is_active:
                return user
    return None


def _raw_api_key(request: Request) -> str | None:
    header = request.headers.get("X-API-Key")
    if header:
        return header.strip()
    auth = request.headers.get("Authorization") or ""
    if auth.lower().startswith("apikey "):
        return auth.split(" ", 1)[1].strip()
    return None


def get_current_user(
    request: Request,
    token: str | None = Depends(oauth2_scheme),
    db: Session = Depends(get_db),
) -> User:
    credentials_exception = HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="Could not validate credentials",
        headers={"WWW-Authenticate": "Bearer"},
    )
    user: User | None = None
    raw = token or request.cookies.get(settings.cookie_name)
    if raw:
        user = _user_from_jwt(raw, db)
    if not user:
        api_key = _raw_api_key(request)
        if api_key:
            user = _user_from_api_key(api_key, db)
    if not user:
        raise credentials_exception

    # Update real-time presence
    try:
        ip = request.headers.get("x-forwarded-for")
        if ip:
            ip = ip.split(",")[0].strip()
        elif request.client:
            ip = request.client.host
        else:
            ip = "127.0.0.1"
        ua = request.headers.get("user-agent", "")
        path = request.url.path if hasattr(request, "url") else "/"
        presence_manager.touch(
            user_id=user.id,
            username=user.username,
            role=user.role,
            email=user.email,
            avatar=user.avatar,
            ip=ip,
            user_agent=ua,
            current_path=path,
        )
    except Exception:
        pass

    return user


def get_optional_user(
    request: Request,
    token: str | None = Depends(oauth2_scheme),
    db: Session = Depends(get_db),
) -> User | None:
    """Like ``get_current_user`` but returns ``None`` instead of 401."""
    raw = token or request.cookies.get(settings.cookie_name)
    if raw:
        user = _user_from_jwt(raw, db)
        if user:
            return user
    api_key = _raw_api_key(request)
    if api_key:
        return _user_from_api_key(api_key, db)
    return None


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
