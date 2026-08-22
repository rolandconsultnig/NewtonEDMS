"""Enterprise Audit Logging & Compliance Engine."""

import hashlib
import json
from datetime import datetime, timezone
from typing import Any

from fastapi import Request
from sqlalchemy.orm import Session

from app.database import now
from app.models import AuditLog, User


def get_client_ip(request: Request | None) -> str:
    if not request:
        return "127.0.0.1"
    forwarded = request.headers.get("x-forwarded-for")
    if forwarded:
        return forwarded.split(",")[0].strip()
    if request.client:
        return request.client.host
    return "127.0.0.1"


def get_client_ua(request: Request | None) -> str:
    if not request:
        return ""
    return request.headers.get("user-agent", "")[:500]


def calculate_audit_checksum(
    timestamp_str: str,
    username: str,
    action: str,
    resource_type: str,
    resource_id: str,
    severity: str,
    status: str,
    details: str,
) -> str:
    payload = f"{timestamp_str}|{username}|{action}|{resource_type}|{resource_id}|{severity}|{status}|{details}"
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def audit(
    db: Session,
    user: User | None,
    action: str,
    resource_type: str | None = None,
    resource_id: int | None = None,
    details: str = "",
    ip: str | None = None,
    request: Request | None = None,
    severity: str = "INFO",
    status: str = "SUCCESS",
    details_json: dict[str, Any] | list[Any] | None = None,
    resource_name: str | None = None,
    user_agent: str | None = None,
) -> AuditLog:
    """Record an enterprise audit event with cryptographic integrity seal."""
    resolved_ip = ip or get_client_ip(request)
    resolved_ua = user_agent or get_client_ua(request)
    current_time = now()
    username = user.username if user else "SYSTEM"
    actor_role = user.role if user else "system"

    checksum = calculate_audit_checksum(
        timestamp_str=current_time.isoformat(),
        username=username,
        action=action,
        resource_type=resource_type or "",
        resource_id=str(resource_id or ""),
        severity=severity,
        status=status,
        details=details,
    )

    log = AuditLog(
        user_id=user.id if user else None,
        username=username,
        actor_role=actor_role,
        action=action,
        resource_type=resource_type,
        resource_id=resource_id,
        resource_name=resource_name,
        severity=severity,
        status=status,
        details=details,
        details_json=details_json or {},
        ip=resolved_ip,
        user_agent=resolved_ua,
        checksum=checksum,
        timestamp=current_time,
    )
    db.add(log)
    try:
        db.commit()
        db.refresh(log)
    except Exception:
        db.rollback()
    return log

