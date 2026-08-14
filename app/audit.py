"""Audit-log helper."""

from typing import Optional

from sqlalchemy.orm import Session

from app.models import AuditLog, User


def audit(
    db: Session,
    user: Optional[User],
    action: str,
    resource_type: Optional[str] = None,
    resource_id: Optional[int] = None,
    details: str = "",
    ip: Optional[str] = None,
) -> None:
    log = AuditLog(
        user_id=user.id if user else None,
        action=action,
        resource_type=resource_type,
        resource_id=resource_id,
        details=details,
        ip=ip,
    )
    db.add(log)
    db.commit()
