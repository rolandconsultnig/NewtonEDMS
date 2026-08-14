"""Audit-log helper."""


from sqlalchemy.orm import Session

from app.models import AuditLog, User


def audit(
    db: Session,
    user: User | None,
    action: str,
    resource_type: str | None = None,
    resource_id: int | None = None,
    details: str = "",
    ip: str | None = None,
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
