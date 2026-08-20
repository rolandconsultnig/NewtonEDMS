"""OpenID Connect authorization-code flow (Keycloak and other OIDC providers)."""
from __future__ import annotations

import logging
import secrets
from datetime import timedelta
from urllib.parse import urlencode

from fastapi import HTTPException
from sqlalchemy.orm import Session

from app.config import settings
from app.database import now
from app.models import OidcState, User
from app.security import get_password_hash

logger = logging.getLogger("newtonedms.oidc")


def enabled() -> bool:
    return bool(settings.oidc_issuer and settings.oidc_client_id)


def _discover() -> dict:
    import httpx

    issuer = settings.oidc_issuer.rstrip("/")
    url = issuer + "/.well-known/openid-configuration"
    r = httpx.get(url, timeout=10.0)
    r.raise_for_status()
    return r.json()


def authorization_url(db: Session, redirect_uri: str | None = None) -> str:
    if not enabled():
        raise HTTPException(status_code=400, detail="OIDC is not configured")
    meta = _discover()
    state = secrets.token_urlsafe(24)
    nonce = secrets.token_urlsafe(24)
    row = OidcState(state=state, nonce=nonce, expires_at=now() + timedelta(minutes=10))
    db.add(row)
    db.commit()
    params = {
        "response_type": "code",
        "client_id": settings.oidc_client_id,
        "redirect_uri": redirect_uri or settings.oidc_redirect_uri,
        "scope": "openid profile email",
        "state": state,
        "nonce": nonce,
    }
    return meta["authorization_endpoint"] + "?" + urlencode(params)


def exchange_code(db: Session, code: str, state: str, redirect_uri: str | None = None) -> User:
    row = db.query(OidcState).filter(OidcState.state == state).first()
    if not row or row.expires_at < now():
        raise HTTPException(status_code=400, detail="Invalid or expired OIDC state")
    db.delete(row)
    db.commit()
    meta = _discover()
    import httpx

    token_r = httpx.post(
        meta["token_endpoint"],
        data={
            "grant_type": "authorization_code",
            "code": code,
            "redirect_uri": redirect_uri or settings.oidc_redirect_uri,
            "client_id": settings.oidc_client_id,
            "client_secret": settings.oidc_client_secret,
        },
        timeout=15.0,
    )
    token_r.raise_for_status()
    tokens = token_r.json()
    access = tokens.get("access_token") or ""
    userinfo_url = meta.get("userinfo_endpoint")
    if not userinfo_url:
        raise HTTPException(status_code=502, detail="OIDC provider has no userinfo_endpoint")
    info_r = httpx.get(userinfo_url, headers={"Authorization": f"Bearer {access}"}, timeout=10.0)
    info_r.raise_for_status()
    info = info_r.json()
    sub = str(info.get("sub") or "")
    email = info.get("email") or ""
    preferred = info.get("preferred_username") or (email.split("@")[0] if email else f"oidc_{sub[:8]}")
    if not sub:
        raise HTTPException(status_code=502, detail="OIDC userinfo missing sub")
    user = db.query(User).filter(User.oidc_sub == sub).first()
    if not user and email:
        user = db.query(User).filter(User.email == email).first()
        if user:
            user.oidc_sub = sub
    if not user:
        username = preferred
        n = 1
        while db.query(User).filter(User.username == username).first():
            n += 1
            username = f"{preferred}{n}"
        user = User(
            username=username,
            email=email or None,
            hashed_password=get_password_hash(secrets.token_urlsafe(24)),
            role="user",
            is_active=True,
            oidc_sub=sub,
        )
        db.add(user)
    db.commit()
    db.refresh(user)
    return user
