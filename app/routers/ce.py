"""Community-parity APIs: trash, clipboard, aliases, ACL bits, tickets, admin."""
from __future__ import annotations

import hashlib
import io
import json
import logging
import secrets
import shutil
import zipfile
from datetime import timedelta
from pathlib import Path

from fastapi import APIRouter, Depends, File, Form, HTTPException, Query, Request, UploadFile
from fastapi.responses import FileResponse, StreamingResponse
from pydantic import BaseModel
from sqlalchemy import func, or_
from sqlalchemy.orm import Session

from app.acl import ACL_BITS, apply_flags, flags_from_bits
from app.audit import audit
from app.config import settings
from app.crypto import encrypt_secret
from app.database import STORAGE_DIR, get_db, now
from app.indexing import index_document, remove_document, search_documents
from app.models import (
    ApiKey,
    AuditLog,
    AuthSession,
    Bookmark,
    CustomFieldValue,
    Document,
    DocumentLink,
    Folder,
    FolderTemplate,
    InternalMessage,
    LoginHistory,
    NamingScheme,
    Permission,
    ScheduledTask,
    ShareLink,
    StorageStore,
    Subscription,
    SystemSetting,
    TrustedDevice,
    User,
    WorkflowTemplate,
    WorkflowTrigger,
)
from app.permissions import has_permission
from app.security import get_current_user, get_password_hash, require_role, verify_password
from app.storage import doc_storage_dir, save_upload, validate_upload_filename

logger = logging.getLogger("newtonedms.ce")
router = APIRouter(prefix="/api", tags=["community"])
open_ce = APIRouter(tags=["community_open"])

ACL_NAMES = list(ACL_BITS.keys())


def _doc(db, doc_id, user, action="read") -> Document:
    d = db.get(Document, doc_id)
    if not d:
        raise HTTPException(404, "Document not found")
    f = db.get(Folder, d.folder_id)
    if not has_permission(db, user, action, f, d):
        raise HTTPException(403, "No permission")
    return d


def _folder(db, folder_id, user, action="read") -> Folder:
    f = db.get(Folder, folder_id)
    if not f:
        raise HTTPException(404, "Folder not found")
    if not has_permission(db, user, action, f):
        raise HTTPException(403, "No permission")
    return f


def _notify_subs(db, resource_type, resource_id, message):
    subs = (
        db.query(Subscription)
        .filter(Subscription.resource_type == resource_type, Subscription.resource_id == resource_id)
        .all()
    )
    from app.models import Notification

    for s in subs:
        db.add(Notification(user_id=s.user_id, message=message))
    if subs:
        db.commit()


# ---- Trash -----------------------------------------------------------------
@router.get("/trash/documents")
def trash_documents(db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    q = db.query(Document).filter(Document.deleted_at.isnot(None))
    if user.role not in ("superadmin", "admin"):
        q = q.filter(or_(Document.deleted_by == user.id, Document.created_by == user.id))
    return q.order_by(Document.deleted_at.desc()).limit(500).all()


@router.get("/trash/folders")
def trash_folders(db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    q = db.query(Folder).filter(Folder.deleted_at.isnot(None))
    if user.role not in ("superadmin", "admin"):
        q = q.filter(or_(Folder.deleted_by == user.id, Folder.created_by == user.id))
    return q.order_by(Folder.deleted_at.desc()).limit(500).all()


@router.post("/trash/documents/{doc_id}/restore")
def restore_document(doc_id: int, db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    d = db.get(Document, doc_id)
    if not d or not d.deleted_at:
        raise HTTPException(404, "Not in trash")
    d.deleted_at = None
    d.deleted_by = None
    db.commit()
    audit(db, user, "DOCUMENT_RESTORE", "document", doc_id, d.name)
    return {"ok": True}


def _restore_folder_tree(db, folder: Folder):
    folder.deleted_at = None
    folder.deleted_by = None
    db.query(Document).filter(Document.folder_id == folder.id, Document.deleted_at.isnot(None)).update(
        {"deleted_at": None, "deleted_by": None}
    )
    for child in db.query(Folder).filter(Folder.parent_id == folder.id, Folder.deleted_at.isnot(None)).all():
        _restore_folder_tree(db, child)


@router.post("/trash/folders/{folder_id}/restore")
def restore_folder(folder_id: int, db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    f = db.get(Folder, folder_id)
    if not f or not f.deleted_at:
        raise HTTPException(404, "Not in trash")
    _restore_folder_tree(db, f)
    db.commit()
    audit(db, user, "FOLDER_RESTORE", "folder", folder_id, f.name)
    return {"ok": True}


@router.delete("/trash/folders/{folder_id}")
def purge_folder(folder_id: int, db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    f = db.get(Folder, folder_id)
    if not f or not f.deleted_at:
        raise HTTPException(404, "Not in trash")
    db.delete(f)
    db.commit()
    return {"ok": True}


@router.delete("/trash/documents/{doc_id}")
def purge_document(doc_id: int, db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    from app.routers.documents import delete_document

    return delete_document(doc_id=doc_id, permanent=True, db=db, user=user)


@router.post("/trash/empty")
def empty_trash(db: Session = Depends(get_db), user: User = Depends(require_role("superadmin", "admin"))):
    n = 0
    for d in db.query(Document).filter(Document.deleted_at.isnot(None)).all():
        ddir = doc_storage_dir(d.id)
        if ddir.exists():
            shutil.rmtree(ddir, ignore_errors=True)
        remove_document(d.id)
        db.delete(d)
        n += 1
    for f in db.query(Folder).filter(Folder.deleted_at.isnot(None)).all():
        db.delete(f)
        n += 1
    db.commit()
    return {"purged": n}


# ---- Clipboard / move / copy / merge --------------------------------------
class ClipboardOp(BaseModel):
    ids: list[int]
    target_folder_id: int
    as_alias: bool = False


@router.post("/documents/copy")
def copy_documents(payload: ClipboardOp, db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    target = _folder(db, payload.target_folder_id, user, "write")
    created = []
    for doc_id in payload.ids:
        src = _doc(db, doc_id, user, "read")
        if payload.as_alias:
            alias = Document(
                name=src.name,
                title=src.title,
                folder_id=target.id,
                current_version=src.current_version,
                status=src.status,
                size=src.size,
                mime=src.mime,
                file_path=src.file_path,
                tags=src.tags,
                created_by=user.id,
                alias_of_id=src.alias_of_id or src.id,
            )
            db.add(alias)
            db.commit()
            db.refresh(alias)
            created.append(alias.id)
            continue
        dest = doc_storage_dir(0)
        # create row first then copy files
        copy = Document(
            name=src.name,
            title=src.title,
            folder_id=target.id,
            current_version=1,
            status="draft",
            size=src.size,
            mime=src.mime,
            file_path=src.file_path,
            tags=src.tags,
            metadata_json=src.metadata_json or {},
            created_by=user.id,
            source="copy",
        )
        db.add(copy)
        db.commit()
        db.refresh(copy)
        ddir = doc_storage_dir(copy.id)
        ddir.mkdir(parents=True, exist_ok=True)
        src_path = Path(src.file_path) if src.file_path else None
        if src_path and src_path.exists():
            dest_path = ddir / src_path.name
            shutil.copy2(src_path, dest_path)
            copy.file_path = str(dest_path)
            db.commit()
        created.append(copy.id)
    audit(db, user, "DOCUMENT_COPY", "folder", target.id, f"Copied {created}")
    return {"ids": created}


@router.post("/documents/move")
def move_documents(payload: ClipboardOp, db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    target = _folder(db, payload.target_folder_id, user, "write")
    for doc_id in payload.ids:
        d = _doc(db, doc_id, user, "delete")
        if d.immutable:
            raise HTTPException(400, "Document is immutable")
        d.folder_id = target.id
    db.commit()
    audit(db, user, "DOCUMENT_MOVE", "folder", target.id, str(payload.ids))
    return {"ok": True, "ids": payload.ids}


class FolderOp(BaseModel):
    folder_id: int
    target_folder_id: int
    as_alias: bool = False


@router.post("/folders/move")
def move_folder(payload: FolderOp, db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    f = _folder(db, payload.folder_id, user, "delete")
    target = _folder(db, payload.target_folder_id, user, "write")
    if f.parent_id is None:
        raise HTTPException(400, "Cannot move root")
    if payload.target_folder_id == f.id:
        raise HTTPException(400, "Cannot move into itself")
    f.parent_id = target.id
    db.commit()
    return {"ok": True}


@router.post("/folders/copy")
def copy_folder(payload: FolderOp, db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    src = _folder(db, payload.folder_id, user, "read")
    target = _folder(db, payload.target_folder_id, user, "write")
    if payload.as_alias:
        alias = Folder(
            name=src.name,
            parent_id=target.id,
            is_public=False,
            created_by=user.id,
            alias_of_id=src.alias_of_id or src.id,
            kind="folder",
        )
        db.add(alias)
        db.commit()
        db.refresh(alias)
        return {"id": alias.id, "alias": True}
    copy = Folder(name=src.name + " (copy)", parent_id=target.id, is_public=src.is_public, created_by=user.id, kind=src.kind)
    db.add(copy)
    db.commit()
    db.refresh(copy)
    return {"id": copy.id}


@router.post("/folders/merge")
def merge_folders(payload: FolderOp, db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    src = _folder(db, payload.folder_id, user, "delete")
    target = _folder(db, payload.target_folder_id, user, "write")
    db.query(Document).filter(Document.folder_id == src.id, Document.deleted_at.is_(None)).update({"folder_id": target.id})
    db.query(Folder).filter(Folder.parent_id == src.id).update({"parent_id": target.id})
    src.deleted_at = now()
    src.deleted_by = user.id
    db.commit()
    return {"ok": True}


@router.post("/folders/{folder_id}/workspace")
def mark_workspace(folder_id: int, db: Session = Depends(get_db), user: User = Depends(require_role("superadmin", "admin", "manager"))):
    f = _folder(db, folder_id, user, "manage")
    f.kind = "workspace"
    db.commit()
    return {"ok": True, "kind": f.kind}


# ---- Aliases / links / lock / flags ---------------------------------------
class LinkIn(BaseModel):
    dst_id: int
    kind: str = "related"


@router.get("/documents/{doc_id}/links")
def list_links(doc_id: int, db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    _doc(db, doc_id, user)
    rows = db.query(DocumentLink).filter(or_(DocumentLink.src_id == doc_id, DocumentLink.dst_id == doc_id)).all()
    return [{"id": r.id, "src_id": r.src_id, "dst_id": r.dst_id, "kind": r.kind} for r in rows]


@router.post("/documents/{doc_id}/links")
def add_link(doc_id: int, payload: LinkIn, db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    _doc(db, doc_id, user, "write")
    _doc(db, payload.dst_id, user, "read")
    row = DocumentLink(src_id=doc_id, dst_id=payload.dst_id, kind=payload.kind, created_by=user.id)
    db.add(row)
    db.commit()
    db.refresh(row)
    return {"id": row.id}


@router.delete("/documents/{doc_id}/links/{link_id}")
def del_link(doc_id: int, link_id: int, db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    _doc(db, doc_id, user, "write")
    row = db.get(DocumentLink, link_id)
    if row:
        db.delete(row)
        db.commit()
    return {"ok": True}


@router.get("/documents/{doc_id}/aliases")
def list_aliases(doc_id: int, db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    _doc(db, doc_id, user)
    return db.query(Document).filter(Document.alias_of_id == doc_id).all()


@router.post("/documents/{doc_id}/lock")
def lock_doc(doc_id: int, db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    d = _doc(db, doc_id, user, "write")
    if d.locked_by and d.locked_by != user.id and user.role not in ("admin", "superadmin"):
        raise HTTPException(400, "Already locked")
    d.locked_by = user.id
    db.commit()
    return {"ok": True, "locked_by": user.id}


@router.post("/documents/{doc_id}/unlock")
def unlock_doc(doc_id: int, db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    d = _doc(db, doc_id, user, "write")
    if d.locked_by not in (None, user.id) and user.role not in ("admin", "superadmin"):
        raise HTTPException(403, "Locked by another user")
    d.locked_by = None
    db.commit()
    return {"ok": True}


class FlagIn(BaseModel):
    immutable: bool | None = None
    indexable: str | None = None
    rating: int | None = None
    color: str | None = None
    password: str | None = None
    clear_password: bool = False


@router.post("/documents/{doc_id}/flags")
def set_flags(doc_id: int, payload: FlagIn, db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    d = _doc(db, doc_id, user, "manage")
    if payload.immutable is not None:
        d.immutable = payload.immutable
    if payload.indexable:
        d.indexable = payload.indexable
    if payload.rating is not None:
        d.rating = max(0, min(5, payload.rating))
    if payload.color is not None:
        d.color = payload.color
    if payload.clear_password:
        d.file_password_hash = None
    elif payload.password:
        d.file_password_hash = get_password_hash(payload.password)
    db.commit()
    return {"ok": True}


@router.post("/documents/{doc_id}/index-now")
def index_now(doc_id: int, db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    d = _doc(db, doc_id, user, "write")
    if d.indexable == "unindexable":
        remove_document(d.id)
        return {"ok": True, "indexed": False}
    index_document(d.id, d.title, d.tags, d.file_path, d.size or 0)
    return {"ok": True, "indexed": True}


@router.get("/documents/{doc_id}/history")
def doc_history(doc_id: int, db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    _doc(db, doc_id, user)
    return (
        db.query(AuditLog)
        .filter(AuditLog.resource_type == "document", AuditLog.resource_id == doc_id)
        .order_by(AuditLog.timestamp.desc())
        .limit(200)
        .all()
    )


@router.get("/folders/{folder_id}/history")
def folder_history(folder_id: int, db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    _folder(db, folder_id, user)
    return (
        db.query(AuditLog)
        .filter(AuditLog.resource_type == "folder", AuditLog.resource_id == folder_id)
        .order_by(AuditLog.timestamp.desc())
        .limit(200)
        .all()
    )


# ---- Subscriptions / bookmarks --------------------------------------------
class SubIn(BaseModel):
    resource_type: str
    resource_id: int
    events: str = "*"


@router.get("/subscriptions")
def list_subs(db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    return db.query(Subscription).filter(Subscription.user_id == user.id).all()


@router.post("/subscriptions")
def add_sub(payload: SubIn, db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    row = Subscription(user_id=user.id, resource_type=payload.resource_type, resource_id=payload.resource_id, events=payload.events)
    db.add(row)
    db.commit()
    db.refresh(row)
    return row


@router.delete("/subscriptions/{sub_id}")
def del_sub(sub_id: int, db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    row = db.get(Subscription, sub_id)
    if row and row.user_id == user.id:
        db.delete(row)
        db.commit()
    return {"ok": True}


class StarIn(BaseModel):
    kind: str
    resource_id: int
    name: str


@router.post("/stars")
def add_star(payload: StarIn, db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    row = Bookmark(name=payload.name, query="", user_id=user.id, kind=payload.kind, resource_id=payload.resource_id)
    db.add(row)
    db.commit()
    db.refresh(row)
    return row


# ---- ACL 24-bit ------------------------------------------------------------
class AclIn(BaseModel):
    principal_type: str
    principal_id: int
    flags: dict


@router.post("/folders/{folder_id}/acl")
def set_folder_acl(folder_id: int, payload: AclIn, db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    f = _folder(db, folder_id, user, "manage")
    p = (
        db.query(Permission)
        .filter(
            Permission.resource_type == "folder",
            Permission.resource_id == f.id,
            Permission.principal_type == payload.principal_type,
            Permission.principal_id == payload.principal_id,
        )
        .first()
    )
    if not p:
        p = Permission(
            principal_type=payload.principal_type,
            principal_id=payload.principal_id,
            resource_type="folder",
            resource_id=f.id,
        )
        db.add(p)
    apply_flags(p, payload.flags)
    db.commit()
    return {"ok": True, "flags": flags_from_bits(p.bits, p)}


@router.get("/folders/{folder_id}/acl")
def get_folder_acl(folder_id: int, db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    f = _folder(db, folder_id, user, "manage")
    rows = db.query(Permission).filter(Permission.resource_type == "folder", Permission.resource_id == f.id).all()
    return [
        {
            "id": p.id,
            "principal_type": p.principal_type,
            "principal_id": p.principal_id,
            "flags": flags_from_bits(p.bits, p),
            "can_read": p.can_read,
            "can_write": p.can_write,
            "can_delete": p.can_delete,
            "can_manage": p.can_manage,
        }
        for p in rows
    ]


@router.post("/documents/{doc_id}/acl")
def set_document_acl(doc_id: int, payload: AclIn, db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    d = _doc(db, doc_id, user, "manage")
    p = (
        db.query(Permission)
        .filter(
            Permission.resource_type == "document",
            Permission.resource_id == d.id,
            Permission.principal_type == payload.principal_type,
            Permission.principal_id == payload.principal_id,
        )
        .first()
    )
    if not p:
        p = Permission(
            principal_type=payload.principal_type,
            principal_id=payload.principal_id,
            resource_type="document",
            resource_id=d.id,
        )
        db.add(p)
    apply_flags(p, payload.flags)
    db.commit()
    return {"ok": True, "flags": flags_from_bits(p.bits, p)}


@router.get("/documents/{doc_id}/acl")
def get_document_acl(doc_id: int, db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    d = _doc(db, doc_id, user, "manage")
    rows = db.query(Permission).filter(Permission.resource_type == "document", Permission.resource_id == d.id).all()
    return [
        {
            "id": p.id,
            "principal_type": p.principal_type,
            "principal_id": p.principal_id,
            "flags": flags_from_bits(p.bits, p),
            "can_read": p.can_read,
            "can_write": p.can_write,
            "can_delete": p.can_delete,
            "can_manage": p.can_manage,
        }
        for p in rows
    ]


@router.delete("/documents/{doc_id}/acl/{perm_id}")
def delete_document_acl(doc_id: int, perm_id: int, db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    _doc(db, doc_id, user, "manage")
    p = db.get(Permission, perm_id)
    if not p or p.resource_type != "document" or p.resource_id != doc_id:
        raise HTTPException(404, "ACL row not found")
    db.delete(p)
    db.commit()
    return {"ok": True}


@router.get("/acl/bits")
def acl_bit_names():
    return {"bits": ACL_NAMES}


# ---- Tickets / reports ----------------------------------------------------
@router.get("/tickets")
def list_tickets(db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    q = db.query(ShareLink)
    if user.role not in ("superadmin", "admin"):
        q = q.filter(ShareLink.created_by == user.id)
    rows = q.order_by(ShareLink.created_at.desc()).limit(500).all()
    return [
        {
            "id": s.id,
            "token": s.token,
            "document_id": s.document_id,
            "kind": s.kind or "download",
            "name": s.name,
            "expires_at": s.expires_at,
            "download_count": s.download_count,
            "max_downloads": s.max_downloads,
            "password_protected": bool(s.password_hash),
            "url": f"/api/shares/{s.token}",
        }
        for s in rows
    ]


@router.get("/reports/locked")
def report_locked(db: Session = Depends(get_db), user: User = Depends(require_role("superadmin", "admin"))):
    return db.query(Document).filter(or_(Document.locked_by.isnot(None), Document.checked_out_by.isnot(None)), Document.deleted_at.is_(None)).all()


@router.get("/reports/deleted")
def report_deleted(db: Session = Depends(get_db), user: User = Depends(require_role("superadmin", "admin"))):
    return {
        "documents": db.query(Document).filter(Document.deleted_at.isnot(None)).limit(500).all(),
        "folders": db.query(Folder).filter(Folder.deleted_at.isnot(None)).limit(500).all(),
    }


@router.get("/reports/duplicates")
def report_duplicates(db: Session = Depends(get_db), user: User = Depends(require_role("superadmin", "admin"))):
    return db.query(Document).filter(Document.duplicate_of.isnot(None), Document.deleted_at.is_(None)).limit(500).all()


@router.get("/reports/archived")
def report_archived(db: Session = Depends(get_db), user: User = Depends(require_role("superadmin", "admin"))):
    return db.query(Document).filter(Document.status == "archived", Document.deleted_at.is_(None)).limit(500).all()


@router.get("/reports/last-changes")
def report_changes(db: Session = Depends(get_db), user: User = Depends(require_role("superadmin", "admin"))):
    return db.query(AuditLog).order_by(AuditLog.timestamp.desc()).limit(200).all()


@router.get("/reports/subscriptions")
def report_subs(db: Session = Depends(get_db), user: User = Depends(require_role("superadmin", "admin"))):
    return db.query(Subscription).all()


@router.get("/reports/api-calls")
def report_api(db: Session = Depends(get_db), user: User = Depends(require_role("superadmin", "admin"))):
    rows = (
        db.query(AuditLog.action, func.count(AuditLog.id))
        .group_by(AuditLog.action)
        .order_by(func.count(AuditLog.id).desc())
        .limit(50)
        .all()
    )
    return [{"action": a, "count": c} for a, c in rows]


# ---- Messages / quota / working time / profile -----------------------------
class MessageIn(BaseModel):
    to_id: int
    subject: str
    body: str = ""


@router.get("/messages")
def list_messages(db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    return (
        db.query(InternalMessage)
        .filter(or_(InternalMessage.to_id == user.id, InternalMessage.from_id == user.id))
        .order_by(InternalMessage.created_at.desc())
        .limit(200)
        .all()
    )


@router.post("/messages")
def send_message(payload: MessageIn, db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    row = InternalMessage(from_id=user.id, to_id=payload.to_id, subject=payload.subject, body=payload.body)
    db.add(row)
    db.commit()
    db.refresh(row)
    return row


@router.post("/messages/{msg_id}/read")
def read_message(msg_id: int, db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    row = db.get(InternalMessage, msg_id)
    if row and row.to_id == user.id:
        row.read = True
        db.commit()
    return {"ok": True}


@router.get("/quota")
def get_quota(db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    used = db.query(func.coalesce(func.sum(Document.size), 0)).filter(Document.created_by == user.id, Document.deleted_at.is_(None)).scalar() or 0
    return {"used": used, "limit": user.quota_bytes or 0}


class QuotaIn(BaseModel):
    user_id: int
    quota_bytes: int


@router.post("/quota")
def set_quota(payload: QuotaIn, db: Session = Depends(get_db), user: User = Depends(require_role("superadmin", "admin"))):
    u = db.get(User, payload.user_id)
    if not u:
        raise HTTPException(404, "User not found")
    u.quota_bytes = payload.quota_bytes
    db.commit()
    return {"ok": True}


class ProfileIn(BaseModel):
    email: str | None = None
    locale: str | None = None
    density: str | None = None
    avatar: str | None = None
    working_hours: dict | None = None
    password: str | None = None
    current_password: str | None = None


@router.put("/profile")
def update_profile(payload: ProfileIn, db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    if payload.email is not None:
        user.email = payload.email
    if payload.locale:
        user.locale = payload.locale
    if payload.density:
        user.density = payload.density
    if payload.avatar is not None:
        user.avatar = payload.avatar
    if payload.working_hours is not None:
        user.working_hours = payload.working_hours
    if payload.password:
        if not payload.current_password or not verify_password(payload.current_password, user.hashed_password):
            raise HTTPException(400, "Current password required")
        from app.security import validate_password_strength

        validate_password_strength(payload.password)
        user.hashed_password = get_password_hash(payload.password)
    db.commit()
    return {"ok": True}


@router.get("/logins")
def last_logins(db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    return (
        db.query(LoginHistory)
        .filter(LoginHistory.user_id == user.id)
        .order_by(LoginHistory.created_at.desc())
        .limit(50)
        .all()
    )


@router.get("/sessions")
def list_sessions(db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    q = db.query(AuthSession).filter(AuthSession.revoked.is_(False))
    if user.role not in ("superadmin", "admin"):
        q = q.filter(AuthSession.user_id == user.id)
    return q.order_by(AuthSession.last_seen_at.desc()).limit(200).all()


@router.delete("/sessions/{session_id}")
def revoke_session(session_id: int, db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    s = db.get(AuthSession, session_id)
    if not s:
        raise HTTPException(404, "Not found")
    if s.user_id != user.id and user.role not in ("admin", "superadmin"):
        raise HTTPException(403, "No permission")
    s.revoked = True
    db.commit()
    return {"ok": True}


class DeviceIn(BaseModel):
    fingerprint: str
    name: str = ""


@router.get("/devices")
def list_devices(db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    return db.query(TrustedDevice).filter(TrustedDevice.user_id == user.id).all()


@router.post("/devices")
def add_device(payload: DeviceIn, db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    row = TrustedDevice(user_id=user.id, fingerprint=payload.fingerprint, name=payload.name)
    db.add(row)
    db.commit()
    db.refresh(row)
    return row


@router.delete("/devices/{device_id}")
def del_device(device_id: int, db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    row = db.get(TrustedDevice, device_id)
    if row and row.user_id == user.id:
        db.delete(row)
        db.commit()
    return {"ok": True}


class ApiKeyIn(BaseModel):
    name: str


@router.get("/apikeys")
@router.get("/api-keys")
@open_ce.get("/apikeys")
@open_ce.get("/api-keys")
def list_keys(db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    rows = db.query(ApiKey).filter(ApiKey.user_id == user.id).all()
    return [{"id": k.id, "name": k.name, "prefix": k.prefix, "created_at": k.created_at, "last_used_at": k.last_used_at} for k in rows]


@router.post("/apikeys")
@router.post("/api-keys")
@open_ce.post("/apikeys")
@open_ce.post("/api-keys")
def create_key(payload: ApiKeyIn, db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    raw = secrets.token_urlsafe(32)
    prefix = raw[:8]
    row = ApiKey(user_id=user.id, name=payload.name, prefix=prefix, key_hash=get_password_hash(raw))
    db.add(row)
    db.commit()
    db.refresh(row)
    return {"id": row.id, "name": row.name, "prefix": prefix, "secret": raw}


@router.delete("/apikeys/{key_id}")
@router.delete("/api-keys/{key_id}")
@open_ce.delete("/apikeys/{key_id}")
@open_ce.delete("/api-keys/{key_id}")
def delete_key(key_id: int, db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    row = db.get(ApiKey, key_id)
    if row and row.user_id == user.id:
        db.delete(row)
        db.commit()
    return {"ok": True}


# ---- Settings / OCR / GUI / LDAP / stores / tasks / index -----------------
def _setting(db, key, default=""):
    row = db.get(SystemSetting, key)
    return row.value if row else default


def _set(db, key, value):
    row = db.get(SystemSetting, key)
    if not row:
        row = SystemSetting(key=key, value=value)
        db.add(row)
    else:
        row.value = value
        row.updated_at = now()
    db.commit()
    return row


@router.get("/settings/{key}")
def get_setting(key: str, db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    return {"key": key, "value": _setting(db, key)}


class SettingIn(BaseModel):
    value: str | dict | list | int | bool | None = ""


@router.put("/settings/{key}")
def put_setting(key: str, payload: SettingIn, db: Session = Depends(get_db), user: User = Depends(require_role("superadmin", "admin"))):
    val = payload.value if isinstance(payload.value, str) else json.dumps(payload.value)
    _set(db, key, val)
    return {"ok": True, "key": key, "value": val}


@router.post("/settings/{key}")
def post_setting(key: str, payload: SettingIn, db: Session = Depends(get_db), user: User = Depends(require_role("superadmin", "admin"))):
    val = payload.value if isinstance(payload.value, str) else json.dumps(payload.value)
    _set(db, key, val)
    return {"ok": True, "key": key, "value": val}


@router.get("/settings")
def all_settings(db: Session = Depends(get_db), user: User = Depends(require_role("superadmin", "admin"))):
    return {r.key: r.value for r in db.query(SystemSetting).all()}


@router.post("/index/rebuild")
def rebuild_index(db: Session = Depends(get_db), user: User = Depends(require_role("superadmin", "admin"))):
    n = 0
    for d in db.query(Document).filter(Document.deleted_at.is_(None), Document.indexable != "unindexable").all():
        if d.file_path:
            index_document(d.id, d.title, d.tags, d.file_path, d.size or 0)
            n += 1
    return {"indexed": n}


@router.get("/index/stats")
def index_stats(user: User = Depends(require_role("superadmin", "admin"))):
    from whoosh import index as windex

    path = STORAGE_DIR / "whoosh_index"
    if not path.exists() or not windex.exists_in(path):
        return {"docs": 0, "path": str(path)}
    ix = windex.open_dir(path)
    with ix.searcher() as s:
        return {"docs": s.doc_count(), "path": str(path)}


@router.get("/stores")
def list_stores(db: Session = Depends(get_db), user: User = Depends(require_role("superadmin", "admin"))):
    return db.query(StorageStore).all()


class StoreIn(BaseModel):
    name: str
    kind: str = "fs"
    path: str = ""
    is_default: bool = False
    config: dict | None = None


@router.post("/stores")
def add_store(payload: StoreIn, db: Session = Depends(get_db), user: User = Depends(require_role("superadmin", "admin"))):
    if payload.is_default:
        db.query(StorageStore).update({"is_default": False})
    row = StorageStore(
        name=payload.name,
        kind=payload.kind,
        path=payload.path or "",
        is_default=payload.is_default,
        config=payload.config or {},
    )
    db.add(row)
    db.commit()
    db.refresh(row)
    return row


@router.delete("/stores/{store_id}")
def del_store(store_id: int, db: Session = Depends(get_db), user: User = Depends(require_role("superadmin", "admin"))):
    row = db.get(StorageStore, store_id)
    if row:
        db.delete(row)
        db.commit()
    return {"ok": True}


@router.get("/tasks/scheduled")
def list_sched(db: Session = Depends(get_db), user: User = Depends(require_role("superadmin", "admin"))):
    from app.scheduler import ensure_default_tasks

    ensure_default_tasks(db)
    return db.query(ScheduledTask).all()


class SchedIn(BaseModel):
    enabled: bool | None = None
    interval_minutes: int | None = None


@router.put("/tasks/scheduled/{task_id}")
def update_sched(task_id: int, payload: SchedIn, db: Session = Depends(get_db), user: User = Depends(require_role("superadmin", "admin"))):
    t = db.get(ScheduledTask, task_id)
    if not t:
        raise HTTPException(404, "Not found")
    if payload.enabled is not None:
        t.enabled = payload.enabled
    if payload.interval_minutes:
        t.interval_minutes = payload.interval_minutes
    db.commit()
    return t


@router.post("/tasks/scheduled/{task_id}/run")
def run_sched(task_id: int, db: Session = Depends(get_db), user: User = Depends(require_role("superadmin", "admin"))):
    from app.scheduler import run_task

    t = db.get(ScheduledTask, task_id)
    if not t:
        raise HTTPException(404, "Not found")
    run_task(db, t)
    return t


@router.get("/logs")
def get_logs(user: User = Depends(require_role("superadmin", "admin"))):
    log_path = Path("newtonedms.log")
    if not log_path.exists():
        return {"lines": []}
    lines = log_path.read_text(encoding="utf-8", errors="ignore").splitlines()[-200:]
    return {"lines": lines}


@router.post("/system/restart")
def restart_hint(user: User = Depends(require_role("superadmin", "admin"))):
    return {"ok": True, "message": "Stop and start the process to apply runtime changes."}


# ---- Folder templates / naming / triggers / zip / split / convert ---------
class TplIn(BaseModel):
    name: str
    tree: list = []


@router.get("/folder-templates")
def list_ftpl(db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    return db.query(FolderTemplate).all()


@router.post("/folder-templates")
def add_ftpl(payload: TplIn, db: Session = Depends(get_db), user: User = Depends(require_role("superadmin", "admin", "manager"))):
    row = FolderTemplate(name=payload.name, tree=payload.tree, created_by=user.id)
    db.add(row)
    db.commit()
    db.refresh(row)
    return row


@router.post("/folders/{folder_id}/apply-template/{template_id}")
def apply_ftpl(folder_id: int, template_id: int, db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    parent = _folder(db, folder_id, user, "write")
    tpl = db.get(FolderTemplate, template_id)
    if not tpl:
        raise HTTPException(404, "Template not found")

    def walk(nodes, pid):
        for n in nodes or []:
            f = Folder(name=n.get("name", "Folder"), parent_id=pid, created_by=user.id, is_public=False)
            db.add(f)
            db.flush()
            walk(n.get("children") or [], f.id)

    walk(tpl.tree or [], parent.id)
    db.commit()
    return {"ok": True}


class TriggerIn(BaseModel):
    template_id: int
    event: str = "create"


@router.get("/folders/{folder_id}/triggers")
def list_triggers(folder_id: int, db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    _folder(db, folder_id, user)
    return db.query(WorkflowTrigger).filter(WorkflowTrigger.folder_id == folder_id).all()


@router.post("/folders/{folder_id}/triggers")
def add_trigger(folder_id: int, payload: TriggerIn, db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    _folder(db, folder_id, user, "manage")
    row = WorkflowTrigger(folder_id=folder_id, template_id=payload.template_id, event=payload.event)
    db.add(row)
    db.commit()
    db.refresh(row)
    return row


@router.delete("/folders/{folder_id}/triggers/{trigger_id}")
def del_trigger(folder_id: int, trigger_id: int, db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    row = db.get(WorkflowTrigger, trigger_id)
    if row:
        db.delete(row)
        db.commit()
    return {"ok": True}


class SchemeIn(BaseModel):
    name: str
    pattern: str
    folder_id: int | None = None


@router.get("/naming-schemes")
def list_schemes(db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    return db.query(NamingScheme).all()


@router.post("/naming-schemes")
def add_scheme(payload: SchemeIn, db: Session = Depends(get_db), user: User = Depends(require_role("superadmin", "admin"))):
    row = NamingScheme(name=payload.name, pattern=payload.pattern, folder_id=payload.folder_id)
    db.add(row)
    db.commit()
    db.refresh(row)
    return row


@router.post("/folders/{folder_id}/import-zip")
async def import_zip(
    folder_id: int,
    file: UploadFile = File(...),
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    from app.joex import schedule_document
    from app.routers.documents import _parse_dt  # noqa: F401
    from app.storage import safe_filename

    target = _folder(db, folder_id, user, "write")
    data = await file.read()
    imported = 0
    with zipfile.ZipFile(io.BytesIO(data)) as zf:
        for info in zf.infolist():
            if info.is_dir() or info.filename.endswith("/"):
                continue
            name = Path(info.filename).name
            try:
                validate_upload_filename(name)
            except Exception:
                continue
            raw = zf.read(info)
            d = Document(
                name=name,
                title=name,
                folder_id=target.id,
                current_version=1,
                status="draft",
                size=len(raw),
                mime=None,
                file_path="",
                created_by=user.id,
                source="zip",
            )
            db.add(d)
            db.commit()
            db.refresh(d)
            dest = doc_storage_dir(d.id)
            dest.mkdir(parents=True, exist_ok=True)
            path = dest / safe_filename(name)
            path.write_bytes(raw)
            d.file_path = str(path)
            db.commit()
            schedule_document(db, d.id, created_by=user.id)
            imported += 1
    return {"imported": imported}


@router.post("/documents/{doc_id}/split")
def split_doc(doc_id: int, db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    d = _doc(db, doc_id, user, "write")
    path = Path(d.file_path or "")
    created = []
    if path.suffix.lower() != ".pdf":
        raise HTTPException(400, "Split currently supports PDF files")
    try:
        import pdfplumber
        from pypdf import PdfReader, PdfWriter
    except ImportError:
        try:
            from pypdf import PdfReader, PdfWriter
        except ImportError as e:
            raise HTTPException(400, "pypdf is required to split PDFs") from e
    reader = PdfReader(str(path))
    for i, page in enumerate(reader.pages, start=1):
        writer = PdfWriter()
        writer.add_page(page)
        child = Document(
            name=f"{path.stem}_p{i}.pdf",
            title=f"{d.title} p{i}",
            folder_id=d.folder_id,
            current_version=1,
            status="draft",
            size=0,
            mime="application/pdf",
            file_path="",
            created_by=user.id,
            source="split",
        )
        db.add(child)
        db.commit()
        db.refresh(child)
        dest = doc_storage_dir(child.id)
        dest.mkdir(parents=True, exist_ok=True)
        out = dest / child.name
        with out.open("wb") as fh:
            writer.write(fh)
        child.file_path = str(out)
        child.size = out.stat().st_size
        child.page_count = 1
        db.commit()
        created.append(child.id)
    return {"ids": created}


@router.post("/documents/{doc_id}/convert")
def convert_doc(doc_id: int, fmt: str = Query("txt"), db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    d = _doc(db, doc_id, user, "write")
    text = d.extracted_text or ""
    dest = doc_storage_dir(d.id)
    dest.mkdir(parents=True, exist_ok=True)
    if fmt == "txt":
        out = dest / f"{Path(d.name).stem}.txt"
        out.write_text(text, encoding="utf-8")
    else:
        raise HTTPException(400, "Supported converters: txt")
    from app.models import DocumentAttachment

    att = DocumentAttachment(document_id=d.id, name=out.name, file_path=str(out), size=out.stat().st_size, mime="text/plain", role="converted")
    db.add(att)
    db.commit()
    return {"file": out.name, "size": att.size}


@router.post("/folders/{folder_id}/export-archive")
def export_archive(folder_id: int, db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    f = _folder(db, folder_id, user, "read")
    buf = io.BytesIO()
    docs = db.query(Document).filter(Document.folder_id == folder_id, Document.deleted_at.is_(None)).all()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf:
        meta = []
        for d in docs:
            if d.file_path and Path(d.file_path).exists():
                zf.write(d.file_path, arcname=d.name)
            meta.append({"id": d.id, "name": d.name, "title": d.title, "tags": d.tags, "custom_id": d.custom_id})
        zf.writestr("manifest.json", json.dumps(meta, indent=2))
    buf.seek(0)
    return StreamingResponse(buf, media_type="application/zip", headers={"Content-Disposition": f'attachment; filename="archive_{f.id}.zip"'})


# ---- Parametric search / tag cloud ----------------------------------------
class ParametricIn(BaseModel):
    folder_id: int | None = None
    status: str | None = None
    tags: list[str] | None = None
    template_id: int | None = None
    fields: dict | None = None
    created_from: str | None = None
    created_to: str | None = None
    immutable: bool | None = None
    locked: bool | None = None


@router.post("/search/parametric")
def parametric_search(payload: ParametricIn, db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    q = db.query(Document).filter(Document.deleted_at.is_(None))
    if payload.folder_id:
        q = q.filter(Document.folder_id == payload.folder_id)
    if payload.status:
        q = q.filter(Document.status == payload.status)
    for t in payload.tags or []:
        q = q.filter(Document.tags.ilike(f"%{t}%"))
    if payload.immutable is True:
        q = q.filter(Document.immutable.is_(True))
    if payload.locked is True:
        q = q.filter(Document.locked_by.isnot(None))
    if payload.created_from:
        q = q.filter(Document.created_at >= payload.created_from)
    if payload.created_to:
        q = q.filter(Document.created_at <= payload.created_to)
    if payload.fields:
        for fid, val in payload.fields.items():
            if not val:
                continue
            try:
                field_id = int(fid)
            except (TypeError, ValueError):
                field_id = 0
            fv = db.query(CustomFieldValue).filter(CustomFieldValue.value.ilike(f"%{val}%"))
            if field_id > 0:
                fv = fv.filter(CustomFieldValue.field_id == field_id)
            ids = [r.document_id for r in fv.all()]
            q = q.filter(Document.id.in_(ids or [-1]))
    return q.order_by(Document.updated_at.desc()).limit(200).all()


@router.get("/tags/cloud")
def tag_cloud(db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    counts: dict[str, int] = {}
    for tags in db.query(Document.tags).filter(Document.deleted_at.is_(None)).all():
        for t in (tags[0] or "").split(","):
            t = t.strip()
            if t:
                counts[t] = counts.get(t, 0) + 1
    return sorted(({"name": k, "count": v} for k, v in counts.items()), key=lambda x: -x["count"])


# ---- Preview --------------------------------------------------------------
@router.get("/documents/{doc_id}/preview")
def preview_doc(doc_id: int, db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    d = _doc(db, doc_id, user, "read")
    path = Path(d.pdf_file_path or d.file_path or "")
    if not path.exists():
        raise HTTPException(404, "No file")
    mime = d.mime or "application/octet-stream"
    return FileResponse(path, media_type=mime, filename=d.name, content_disposition_type="inline")


class GraphIn(BaseModel):
    graph: dict
    steps: list | None = None


@router.put("/workflows/{workflow_id}/graph")
def save_graph(workflow_id: int, payload: GraphIn, db: Session = Depends(get_db), user: User = Depends(require_role("superadmin", "admin", "manager"))):
    wf = db.get(WorkflowTemplate, workflow_id)
    if not wf:
        raise HTTPException(404, "Not found")
    wf.graph = payload.graph
    if payload.steps is not None:
        wf.steps = payload.steps
    db.commit()
    return {"ok": True}


@router.get("/converters")
def list_converters(user: User = Depends(require_role("superadmin", "admin"))):
    from app.tools_status import installed_tools

    return installed_tools()


@router.post("/ldap/test")
def ldap_test(db: Session = Depends(get_db), user: User = Depends(require_role("superadmin", "admin"))):
    cfg = _setting(db, "ldap")
    if not cfg:
        raise HTTPException(400, "Save LDAP settings first")
    try:
        data = json.loads(cfg)
    except Exception as e:
        raise HTTPException(400, "Invalid LDAP JSON") from e
    url = data.get("url") or ""
    if not url:
        raise HTTPException(400, "LDAP URL required")
    try:
        import ldap3

        server = ldap3.Server(url, get_info=ldap3.NONE)
        conn = ldap3.Connection(server, user=data.get("bind_dn"), password=data.get("bind_password"), auto_bind=True)
        conn.unbind()
        return {"ok": True, "message": "Bind succeeded"}
    except ImportError:
        return {"ok": False, "message": "ldap3 not installed; settings stored"}
    except Exception as e:
        raise HTTPException(400, str(e)) from e
