"""Authentication routes."""
from datetime import UTC, datetime, timedelta

from fastapi import APIRouter, Depends, Form, Header, HTTPException, Request, Response, status
from fastapi.security import OAuth2PasswordRequestForm
from sqlalchemy.orm import Session

from app.audit import audit
from app.config import settings
from app.database import get_db, now
from app.limiter import limiter
from app.models import AuthSession, LoginHistory, RevokedToken, User
from app.schemas import SessionOut, Token, UserOut
from app.security import (
    create_access_token,
    decode_token,
    get_current_user,
    get_optional_user,
    get_password_hash,
    get_token,
    validate_password_strength,
    verify_password,
)
from app.totp import verify_totp

router = APIRouter(prefix="/api/auth", tags=["auth"])


def _try_ldap(db: Session, username: str, password: str) -> bool:
    from app.models import Group, SystemSetting

    row = db.get(SystemSetting, "ldap")
    if not row or not row.value:
        return False
    try:
        import json

        cfg = json.loads(row.value)
        import ldap3

        server = ldap3.Server(cfg.get("url"), get_info=ldap3.NONE)
        bind_user = (cfg.get("user_dn_pattern") or "uid={username},{base}").format(
            username=username, base=cfg.get("base_dn") or ""
        )
        conn = ldap3.Connection(server, user=bind_user, password=password, auto_bind=True)
        user = db.query(User).filter(User.username == username).first()
        if not user:
            user = User(
                username=username,
                hashed_password=get_password_hash(password + "ldap"),
                role="user",
                ldap_dn=bind_user,
            )
            db.add(user)
            db.flush()
        _sync_ldap_groups(db, user, conn, cfg, bind_user)
        conn.unbind()
        db.commit()
        return True
    except Exception:
        return False


def _sync_ldap_groups(db: Session, user: User, conn, cfg: dict, bind_user: str) -> None:
    """Map LDAP group membership onto local groups and optional role."""
    from app.models import Group

    names: list[str] = []
    try:
        attrs = cfg.get("user_attributes") or ["memberOf", "cn"]
        if conn.search(bind_user, "(objectClass=*)", attributes=attrs):
            entry = conn.entries[0] if conn.entries else None
            if entry is not None and hasattr(entry, "memberOf"):
                for dn in list(entry.memberOf.values) if hasattr(entry.memberOf, "values") else []:
                    cn = ""
                    for part in str(dn).split(","):
                        if part.lower().startswith("cn="):
                            cn = part[3:]
                            break
                    if cn:
                        names.append(cn)
    except Exception:
        pass
    group_base = cfg.get("group_base") or cfg.get("base_dn") or ""
    group_filter = cfg.get("group_filter") or "(member={dn})"
    if group_base:
        try:
            flt = group_filter.format(dn=bind_user, username=user.username)
            if conn.search(group_base, flt, attributes=["cn"]):
                for entry in conn.entries:
                    cn = str(getattr(entry, "cn", "") or "")
                    if cn:
                        names.append(cn)
        except Exception:
            pass
    role_map = cfg.get("role_map") or {}
    seen: set[str] = set()
    for name in names:
        key = name.strip()
        if not key or key.lower() in seen:
            continue
        seen.add(key.lower())
        g = db.query(Group).filter(Group.name == key).first()
        if not g:
            g = Group(name=key, description="LDAP")
            db.add(g)
            db.flush()
        if g not in user.groups:
            user.groups.append(g)
        mapped = role_map.get(key) or role_map.get(key.lower())
        if mapped in ("superadmin", "admin", "manager", "user") and user.role == "user":
            user.role = mapped


def _set_auth_cookie(response: Response, access_token: str, max_age: int | None = None) -> None:
    response.set_cookie(
        key=settings.cookie_name,
        value=access_token,
        httponly=True,
        secure=settings.cookie_secure,
        samesite=settings.cookie_samesite,
        max_age=max_age if max_age is not None else settings.access_token_expire_minutes * 60,
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
    remember: str = Form(""),
    totp_code: str | None = Header(None, alias="X-TOTP"),
    db: Session = Depends(get_db),
):
    from app.security_policy import enforce_request

    enforce_request(db, request)
    user = db.query(User).filter(User.username == form_data.username).first()
    ok = bool(user and verify_password(form_data.password, user.hashed_password))
    if not ok:
        ok = _try_ldap(db, form_data.username, form_data.password)
        if ok:
            user = db.query(User).filter(User.username == form_data.username).first()
    db.add(
        LoginHistory(
            user_id=user.id if user else None,
            username=form_data.username,
            ip=request.client.host if request.client else None,
            user_agent=request.headers.get("user-agent", "")[:250],
            success=bool(ok and user and user.is_active),
        )
    )
    db.commit()
    if not user or not ok:
        if user:
            from app.security_policy import record_failure

            record_failure(db, user)
            db.commit()
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Incorrect username or password",
        )
    if not user.is_active:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED, detail="Account is deactivated"
        )
    from app.security_policy import enforce_request, password_expired, record_success

    enforce_request(db, request, user)
    if password_expired(db, user):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="password_expired")
    record_success(user)
    if user.totp_enabled:
        if not totp_code or not verify_totp(user.totp_secret or "", totp_code):
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="totp_required",
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
    user.last_login_at = now()
    remember_me = str(remember or "").lower() in ("1", "true", "on", "yes")
    minutes = (30 * 24 * 60) if remember_me else settings.access_token_expire_minutes
    access_token = create_access_token(
        {"sub": user.username, "role": user.role},
        expires=timedelta(minutes=minutes),
    )
    try:
        payload = decode_token(access_token)
        db.add(
            AuthSession(
                jti=payload.get("jti") or "",
                user_id=user.id,
                ip=request.client.host if request.client else None,
                user_agent=(request.headers.get("user-agent") or "")[:250],
                expires_at=now(),
            )
        )
    except Exception:
        pass
    db.commit()
    _set_auth_cookie(response, access_token, max_age=minutes * 60)
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


@router.get("/session", response_model=SessionOut)
def session(user: User | None = Depends(get_optional_user)):
    """Session probe for the SPA: always 200 so the console is not spammed with 401s."""
    return {"user": user}


@router.get("/providers")
def auth_providers(db: Session = Depends(get_db)):
    from app.oidc import enabled as oidc_on
    from app.saml import enabled as saml_on

    ldap_row = None
    try:
        from app.models import SystemSetting

        ldap_row = db.get(SystemSetting, "ldap")
    except Exception:
        pass
    ldap_cfg = {}
    if ldap_row and ldap_row.value:
        try:
            import json

            ldap_cfg = json.loads(ldap_row.value) if isinstance(ldap_row.value, str) else {}
        except Exception:
            ldap_cfg = {}
    return {
        "oidc": bool(oidc_on()),
        "saml": bool(saml_on(db)),
        "ldap": bool(ldap_cfg.get("url")),
        "local": True,
    }
