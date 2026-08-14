"""Authentication routes."""
from datetime import UTC, datetime

from fastapi import APIRouter, Depends, HTTPException, Request, Response, status
from fastapi.security import OAuth2PasswordRequestForm
from sqlalchemy.orm import Session

from app.audit import audit
from app.config import settings
from app.database import get_db, now
from app.limiter import limiter
from app.models import RevokedToken, User
from app.schemas import Token, UserOut
from app.security import (
    create_access_token,
    decode_token,
    get_current_user,
    get_password_hash,
    get_token,
    validate_password_strength,
    verify_password,
)

router = APIRouter(prefix="/api/auth", tags=["auth"])


def _set_auth_cookie(response: Response, access_token: str) -> None:
    response.set_cookie(
        key=settings.cookie_name,
        value=access_token,
        httponly=True,
        secure=settings.cookie_secure,
        samesite=settings.cookie_samesite,
        max_age=settings.access_token_expire_minutes * 60,
        path="/",
    )


@router.post("/register", response_model=Token)
@limiter.limit(lambda: settings.register_rate_limit)
def register(
    request: Request,
    response: Response,
    form_data: OAuth2PasswordRequestForm = Depends(),
    db: Session = Depends(get_db),
):
    validate_password_strength(form_data.password)
    if db.query(User).filter(User.username == form_data.username).first():
        raise HTTPException(status_code=400, detail="Username already taken")
    user = User(
        username=form_data.username,
        hashed_password=get_password_hash(form_data.password),
        role="user",
    )
    db.add(user)
    db.commit()
    db.refresh(user)
    audit(db, user, "USER_REGISTER", "user", user.id, f"Registered user {user.username}")
    access_token = create_access_token({"sub": user.username, "role": user.role})
    _set_auth_cookie(response, access_token)
    return {"access_token": access_token, "token_type": "bearer"}


@router.post("/login", response_model=Token)
@limiter.limit(lambda: settings.login_rate_limit)
def login(
    request: Request,
    response: Response,
    form_data: OAuth2PasswordRequestForm = Depends(),
    db: Session = Depends(get_db),
):
    user = db.query(User).filter(User.username == form_data.username).first()
    if not user or not verify_password(form_data.password, user.hashed_password):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Incorrect username or password",
        )
    if not user.is_active:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED, detail="Account is deactivated"
        )
    audit(
        db,
        user,
        "USER_LOGIN",
        "user",
        user.id,
        "Successful login",
        ip=request.client.host if request else None,
    )
    access_token = create_access_token({"sub": user.username, "role": user.role})
    _set_auth_cookie(response, access_token)
    return {"access_token": access_token, "token_type": "bearer"}


@router.post("/logout")
def logout(
    response: Response,
    token: str = Depends(get_token),
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    payload = decode_token(token)
    jti = payload.get("jti")
    exp = payload.get("exp")
    if jti and exp:
        expires_at = datetime.fromtimestamp(exp, tz=UTC).replace(tzinfo=None)
        if not db.query(RevokedToken).filter(RevokedToken.jti == jti).first():
            db.add(RevokedToken(jti=jti, user_id=user.id, expires_at=expires_at))
        # Opportunistic cleanup of already-expired revocation records.
        db.query(RevokedToken).filter(RevokedToken.expires_at < now()).delete()
        db.commit()
    response.delete_cookie(settings.cookie_name, path="/")
    audit(db, user, "USER_LOGOUT", "user", user.id, "Logged out")
    return {"ok": True}


@router.get("/me", response_model=UserOut)
def me(user: User = Depends(get_current_user)):
    return user
