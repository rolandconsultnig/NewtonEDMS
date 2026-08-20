"""Group management and membership routes."""

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from app.audit import audit
from app.database import get_db
from app.models import Group, Permission, User
from app.schemas import GroupCreate, GroupOut
from app.security import get_current_user, require_role

router = APIRouter(prefix="/api/groups", tags=["groups"])


@router.get("", response_model=list[GroupOut])
def list_groups(
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    return db.query(Group).all()


@router.post("", response_model=GroupOut)
def create_group(
    payload: GroupCreate,
    db: Session = Depends(get_db),
    user: User = Depends(require_role("superadmin", "admin")),
):
    g = Group(name=payload.name, description=payload.description)
    db.add(g)
    db.commit()
    db.refresh(g)
    audit(db, user, "GROUP_CREATE", "group", g.id, f"Created group {g.name}")
    return g


@router.put("/{group_id}", response_model=GroupOut)
def update_group(
    group_id: int,
    payload: GroupCreate,
    db: Session = Depends(get_db),
    user: User = Depends(require_role("superadmin", "admin")),
):
    g = db.get(Group, group_id)
    if not g:
        raise HTTPException(status_code=404, detail="Group not found")
    g.name = payload.name
    g.description = payload.description
    db.commit()
    db.refresh(g)
    audit(db, user, "GROUP_UPDATE", "group", g.id, f"Updated group {g.name}")
    return g


@router.delete("/{group_id}")
def delete_group(
    group_id: int,
    db: Session = Depends(get_db),
    user: User = Depends(require_role("superadmin", "admin")),
):
    g = db.get(Group, group_id)
    if not g:
        raise HTTPException(status_code=404, detail="Group not found")
    # Drop ACL rows granted to this group so they cannot linger as dead grants.
    db.query(Permission).filter(
        Permission.principal_type == "group", Permission.principal_id == group_id
    ).delete(synchronize_session=False)
    db.delete(g)  # user_groups association rows are removed by SQLAlchemy
    db.commit()
    audit(db, user, "GROUP_DELETE", "group", group_id, f"Deleted group {g.name}")
    return {"ok": True}


@router.get("/{group_id}/users")
def list_group_users(
    group_id: int,
    db: Session = Depends(get_db),
    current: User = Depends(get_current_user),
):
    g = db.get(Group, group_id)
    if not g:
        raise HTTPException(status_code=404, detail="Group not found")
    return [{"id": u.id, "username": u.username, "role": u.role} for u in g.users]


@router.post("/{group_id}/users/{user_id}")
def add_user_to_group(
    group_id: int,
    user_id: int,
    db: Session = Depends(get_db),
    current: User = Depends(require_role("superadmin", "admin")),
):
    g = db.get(Group, group_id)
    u = db.get(User, user_id)
    if not g or not u:
        raise HTTPException(status_code=404, detail="Group or user not found")
    if u not in g.users:
        g.users.append(u)
        db.commit()
    audit(db, current, "GROUP_ADD_USER", "group", g.id, f"Added {u.username} to {g.name}")
    return {"ok": True}


@router.delete("/{group_id}/users/{user_id}")
def remove_user_from_group(
    group_id: int,
    user_id: int,
    db: Session = Depends(get_db),
    current: User = Depends(require_role("superadmin", "admin")),
):
    g = db.get(Group, group_id)
    u = db.get(User, user_id)
    if not g or not u:
        raise HTTPException(status_code=404, detail="Group or user not found")
    if u in g.users:
        g.users.remove(u)
        db.commit()
    audit(db, current, "GROUP_REMOVE_USER", "group", g.id, f"Removed {u.username} from {g.name}")
    return {"ok": True}
