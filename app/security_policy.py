"""IP allow/deny, geolocation headers, brute-force lockout, password expiry."""
from __future__ import annotations

import ipaddress
import json
from datetime import timedelta

from fastapi import HTTPException, Request
from sqlalchemy.orm import Session

from app.database import now
from app.models import LoginHistory, SystemSetting, User


def load_policy(db: Session) -> dict:
    row = db.get(SystemSetting, "security_policy")
    if not row or not row.value:
        return {}
    try:
        data = json.loads(row.value)
        return data if isinstance(data, dict) else {}
    except json.JSONDecodeError:
        return {}


def _client_ip(request: Request | None) -> str:
    if request is None:
        return ""
    forwarded = request.headers.get("x-forwarded-for") or ""
    if forwarded:
        return forwarded.split(",")[0].strip()
    return request.client.host if request.client else ""


def _ip_in(networks: list, ip: str) -> bool:
    if not ip or not networks:
        return False
    try:
        addr = ipaddress.ip_address(ip)
    except ValueError:
        return ip in {str(n) for n in networks}
    for raw in networks:
        text = str(raw).strip()
        if not text:
            continue
        try:
            if "/" in text:
                if addr in ipaddress.ip_network(text, strict=False):
                    return True
            elif addr == ipaddress.ip_address(text):
                return True
        except ValueError:
            if ip == text:
                return True
    return False


def enforce_request(db: Session, request: Request | None, user: User | None = None) -> None:
    policy = load_policy(db)
    ip = _client_ip(request)
    allow = policy.get("ip_allowlist") or []
    deny = policy.get("ip_denylist") or []
    if deny and _ip_in(deny, ip):
        raise HTTPException(status_code=403, detail="IP address is blocked by security policy")
    if allow and ip and not _ip_in(allow, ip):
        raise HTTPException(status_code=403, detail="IP address is not on the allowlist")
    countries = policy.get("geo_allowlist") or []
    if countries:
        geo = (
            (request.headers.get("cf-ipcountry") if request else None)
            or (request.headers.get("x-geo-country") if request else None)
            or ""
        ).upper()
        allowed = {str(c).upper() for c in countries}
        if geo and geo not in allowed and geo != "XX":
            raise HTTPException(status_code=403, detail="Access from this region is not allowed")
    if user and user.locked_until and user.locked_until > now():
        raise HTTPException(status_code=423, detail="Account is temporarily locked")


def record_failure(db: Session, user: User | None, policy: dict | None = None) -> None:
    policy = policy or (load_policy(db) if user else {})
    if not user:
        return
    user.failed_logins = (user.failed_logins or 0) + 1
    max_fail = int(policy.get("max_failed_logins") or 8)
    lock_minutes = int(policy.get("lockout_minutes") or 15)
    window = now() - timedelta(minutes=lock_minutes)
    recent = (
        db.query(LoginHistory)
        .filter(
            LoginHistory.user_id == user.id,
            LoginHistory.success.is_(False),
            LoginHistory.created_at >= window,
        )
        .count()
    )
    if user.failed_logins >= max_fail or recent >= max_fail:
        user.locked_until = now() + timedelta(minutes=lock_minutes)


def record_success(user: User) -> None:
    user.failed_logins = 0
    user.locked_until = None


def password_expired(db: Session, user: User) -> bool:
    policy = load_policy(db)
    days = int(policy.get("password_max_days") or 0)
    if days <= 0:
        return False
    changed = user.password_changed_at or user.created_at
    if not changed:
        return False
    return (now() - changed) > timedelta(days=days)
