"""Folder and folder-permission routes."""

from typing import Optional

from fastapi import APIRouter, Depends, Form, HTTPException, Query
from sqlalchemy.orm import Session

from app.audit import audit
from app.database import get_db
from app.models import Document, Folder, Permission, RetentionPolicy, User
from app.permissions import has_permission, readable_folder_ids
from app.schemas import FolderCreate, FolderOut, PermissionOut
from app.security import get_current_user

router = APIRouter(prefix="/api/folders", tags=["folders"])


@router.get("", response_model=list[FolderOut])
def list_folders(
    parent_id: Optional[int] = Query(None),
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    root = db.query(Folder).filter(Folder.parent_id.is_(None)).first()
    if parent_id is None:
        parent_id = root.id if root else None
    folders = db.query(Folder).filter(Folder.parent_id == parent_id).all()
    return [f for f in folders if has_permission(db, user, "read", f)]


@router.get("/all", response_model=list[FolderOut])
def list_all_folders(
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    """Every folder the user can read (flat list) — the UI builds the tree client-side."""
    q = db.query(Folder)
    if user.role not in ("superadmin", "admin"):
        ids = readable_folder_ids(db, user)
        if not ids:
            return []
        q = q.filter(Folder.id.in_(ids))
    return q.order_by(Folder.name).all()


@router.post("", response_model=FolderOut)
def create_folder(
    payload: FolderCreate,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    parent = db.get(Folder, payload.parent_id)
    if not parent:
        raise HTTPException(status_code=404, detail="Parent folder not found")
    if not has_permission(db, user, "write", parent):
        raise HTTPException(status_code=403, detail="No permission to create folder here")
    f = Folder(
        name=payload.name,
        parent_id=payload.parent_id,
        is_public=payload.is_public,
        created_by=user.id,
    )
    db.add(f)
    db.commit()
    db.refresh(f)
    # creator has full manage permission
    p = Permission(
        principal_type="user",
        principal_id=user.id,
        resource_type="folder",
        resource_id=f.id,
        can_read=True,
        can_write=True,
        can_delete=True,
        can_manage=True,
    )
    db.add(p)
    db.commit()
    audit(db, user, "FOLDER_CREATE", "folder", f.id, f"Created folder {f.name}")
    return f


@router.get("/{folder_id}", response_model=FolderOut)
def get_folder(
    folder_id: int,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    f = db.get(Folder, folder_id)
    if not f:
        raise HTTPException(status_code=404, detail="Folder not found")
    if not has_permission(db, user, "read", f):
        raise HTTPException(status_code=403, detail="No permission")
    return f


@router.put("/{folder_id}", response_model=FolderOut)
def update_folder(
    folder_id: int,
    payload: FolderCreate,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    f = db.get(Folder, folder_id)
    if not f:
        raise HTTPException(status_code=404, detail="Folder not found")
    if not has_permission(db, user, "manage", f):
        raise HTTPException(status_code=403, detail="No permission to update folder")
    f.name = payload.name
    f.is_public = payload.is_public
    db.commit()
    db.refresh(f)
    audit(db, user, "FOLDER_UPDATE", "folder", f.id, f"Renamed to {f.name}, public={f.is_public}")
    return f


@router.delete("/{folder_id}")
def delete_folder(
    folder_id: int,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    f = db.get(Folder, folder_id)
    if not f:
        raise HTTPException(status_code=404, detail="Folder not found")
    if f.parent_id is None:
        raise HTTPException(status_code=400, detail="Cannot delete root folder")
    if not has_permission(db, user, "delete", f):
        raise HTTPException(status_code=403, detail="No permission to delete folder")
    if db.query(Document).filter(Document.folder_id == folder_id).first() or f.children:
        raise HTTPException(status_code=400, detail="Folder is not empty")
    # Retention policies may outlive their folder; detach the reference.
    db.query(RetentionPolicy).filter(RetentionPolicy.folder_id == folder_id).update(
        {"folder_id": None}
    )
    db.delete(f)
    db.commit()
    audit(db, user, "FOLDER_DELETE", "folder", folder_id, f"Deleted folder {f.name}")
    return {"ok": True}


@router.get("/{folder_id}/permissions", response_model=list[PermissionOut])
def list_folder_permissions(
    folder_id: int,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    f = db.get(Folder, folder_id)
    if not f:
        raise HTTPException(status_code=404, detail="Folder not found")
    if not has_permission(db, user, "manage", f):
        raise HTTPException(status_code=403, detail="No permission")
    return (
        db.query(Permission)
        .filter(Permission.resource_type == "folder", Permission.resource_id == folder_id)
        .all()
    )


@router.post("/{folder_id}/permissions")
def set_folder_permission(
    folder_id: int,
    principal_type: str = Form(..., pattern="^(user|group)$"),
    principal_id: int = Form(...),
    can_read: bool = Form(True),
    can_write: bool = Form(False),
    can_delete: bool = Form(False),
    can_manage: bool = Form(False),
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    f = db.get(Folder, folder_id)
    if not f:
        raise HTTPException(status_code=404, detail="Folder not found")
    if not has_permission(db, user, "manage", f):
        raise HTTPException(status_code=403, detail="No permission")
    p = (
        db.query(Permission)
        .filter(
            Permission.resource_type == "folder",
            Permission.resource_id == folder_id,
            Permission.principal_type == principal_type,
            Permission.principal_id == principal_id,
        )
        .first()
    )
    if not p:
        p = Permission(
            principal_type=principal_type,
            principal_id=principal_id,
            resource_type="folder",
            resource_id=folder_id,
        )
        db.add(p)
    p.can_read = can_read
    p.can_write = can_write
    p.can_delete = can_delete
    p.can_manage = can_manage
    db.commit()
    db.refresh(p)
    audit(
        db, user, "PERMISSION_SET", "folder", folder_id,
        f"Set {principal_type} {principal_id} r={can_read} w={can_write} d={can_delete} m={can_manage}",
    )
    return p
