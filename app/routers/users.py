"""User management routes (admin-only)."""

import json

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from app.audit import audit
from app.database import get_db
from app.models import User
from app.schemas import UserCreate, UserOut, UserUpdate
from app.security import get_password_hash, require_role

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
    db.delete(u)
    db.commit()
    audit(db, current, "USER_DELETE", "user", user_id, f"Deleted user {u.username}")
    return {"ok": True}
