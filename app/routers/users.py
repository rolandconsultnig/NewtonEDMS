"""User management routes (admin-only)."""

import json

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from app import models
from app.audit import audit
from app.database import get_db
from app.models import User
from app.schemas import UserCreate, UserOut, UserUpdate
from app.security import get_password_hash, require_role, validate_password_strength

router = APIRouter(prefix="/api/users", tags=["users"])


@router.get("", response_model=list[UserOut])
def list_users(
    db: Session = Depends(get_db),
    user: User = Depends(require_role("superadmin", "admin")),
):
    return db.query(User).all()


@router.post("", response_model=UserOut)
def create_user(
    payload: UserCreate,
    db: Session = Depends(get_db),
    user: User = Depends(require_role("superadmin", "admin")),
):
    validate_password_strength(payload.password)
    if db.query(User).filter(User.username == payload.username).first():
        raise HTTPException(status_code=400, detail="Username already exists")
    u = User(
        username=payload.username,
        email=payload.email,
        role=payload.role,
        hashed_password=get_password_hash(payload.password),
    )
    db.add(u)
    db.commit()
    db.refresh(u)
    audit(db, user, "USER_CREATE", "user", u.id, f"Created user {u.username}")
    return u


@router.put("/{user_id}", response_model=UserOut)
def update_user(
    user_id: int,
    payload: UserUpdate,
    db: Session = Depends(get_db),
    current: User = Depends(require_role("superadmin", "admin")),
):
    u = db.get(User, user_id)
    if not u:
        raise HTTPException(status_code=404, detail="User not found")
    # Deactivating yourself would invalidate your own session on the next
    # request and lock you out (inactive users cannot log back in).
    if user_id == current.id and payload.is_active is False:
        raise HTTPException(status_code=403, detail="You cannot deactivate your own account")
    for field in ["email", "role", "is_active"]:
        v = getattr(payload, field)
        if v is not None:
            setattr(u, field, v)
    db.commit()
    db.refresh(u)
    audit(db, current, "USER_UPDATE", "user", u.id, json.dumps(payload.model_dump(exclude_unset=True)))
    return u


@router.delete("/{user_id}")
def delete_user(
    user_id: int,
    db: Session = Depends(get_db),
    current: User = Depends(require_role("superadmin", "admin")),
):
    u = db.get(User, user_id)
    if not u:
        raise HTTPException(status_code=404, detail="User not found")
    if user_id == current.id:
        raise HTTPException(status_code=403, detail="You cannot delete your own account")

    # Users who own content are deactivated, never hard-deleted: their documents,
    # folders and version history must keep a valid provenance chain.
    owned = []
    if db.query(models.Document).filter(models.Document.created_by == user_id).first():
        owned.append("documents")
    if db.query(models.Folder).filter(models.Folder.created_by == user_id).first():
        owned.append("folders")
    if db.query(models.DocumentVersion).filter(models.DocumentVersion.created_by == user_id).first():
        owned.append("document versions")
    if owned:
        raise HTTPException(
            status_code=409,
            detail=f"User owns {', '.join(owned)}; deactivate the account instead of deleting it",
        )

    # Detach nullable references (keeps the audit trail, releases checkouts/tasks).
    db.query(models.AuditLog).filter(models.AuditLog.user_id == user_id).update({"user_id": None})
    db.query(models.Document).filter(models.Document.checked_out_by == user_id).update(
        {"checked_out_by": None}
    )
    db.query(models.Task).filter(models.Task.assignee_id == user_id).update({"assignee_id": None})
    # Remove rows that belong solely to the user, in FK-safe order
    # (workflow tasks before their instances, instances before templates).
    db.query(models.Notification).filter(models.Notification.user_id == user_id).delete(
        synchronize_session=False
    )
    db.query(models.Comment).filter(models.Comment.user_id == user_id).delete(
        synchronize_session=False
    )
    db.query(models.ShareLink).filter(models.ShareLink.created_by == user_id).delete(
        synchronize_session=False
    )
    db.query(models.RetentionPolicy).filter(models.RetentionPolicy.created_by == user_id).delete(
        synchronize_session=False
    )
    db.query(models.CalendarEvent).filter(models.CalendarEvent.created_by == user_id).delete(
        synchronize_session=False
    )
    instance_ids = [
        row[0]
        for row in db.query(models.WorkflowInstance.id)
        .filter(models.WorkflowInstance.created_by == user_id)
        .all()
    ]
    if instance_ids:
        db.query(models.Task).filter(models.Task.instance_id.in_(instance_ids)).delete(
            synchronize_session=False
        )
        db.query(models.WorkflowInstance).filter(
            models.WorkflowInstance.id.in_(instance_ids)
        ).delete(synchronize_session=False)
    db.query(models.WorkflowTemplate).filter(
        models.WorkflowTemplate.created_by == user_id
    ).delete(synchronize_session=False)
    db.query(models.RevokedToken).filter(models.RevokedToken.user_id == user_id).delete(
        synchronize_session=False
    )
    db.query(models.Document).filter(models.Document.locked_by == user_id).update(
        {"locked_by": None}
    )
    db.query(models.Document).filter(models.Document.deleted_by == user_id).update(
        {"deleted_by": None}
    )
    for cls in (
        models.AuthSession,
        models.LoginHistory,
        models.ApiKey,
        models.TrustedDevice,
        models.Bookmark,
        models.Dashboard,
        models.Subscription,
        models.NotificationRule,
        models.MailSettings,
    ):
        db.query(cls).filter(cls.user_id == user_id).delete(synchronize_session=False)
    db.query(models.FolderTemplate).filter(models.FolderTemplate.created_by == user_id).delete(
        synchronize_session=False
    )
    db.query(models.InternalMessage).filter(
        (models.InternalMessage.from_id == user_id) | (models.InternalMessage.to_id == user_id)
    ).delete(synchronize_session=False)

    db.delete(u)  # user_groups association rows are removed by SQLAlchemy
    db.commit()
    audit(db, current, "USER_DELETE", "user", user_id, f"Deleted user {u.username}")
    return {"ok": True}
