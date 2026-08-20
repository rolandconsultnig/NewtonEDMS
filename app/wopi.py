"""Microsoft WOPI (Web Application Open Platform Interface) Host Implementation.

Provides standard WOPI endpoints for Office 365, Office Online Server,
Collabora Online, and OnlyOffice to view, edit, and co-author Word (.docx, .doc),
Excel (.xlsx, .xls), and PowerPoint (.pptx, .ppt) documents directly in NewtonEDMS.
"""
from __future__ import annotations

import datetime
import hashlib
import json
import logging
import os
import secrets
import shutil
from pathlib import Path
from typing import Optional

from fastapi import APIRouter, Depends, Header, HTTPException, Query, Request, Response
from fastapi.responses import FileResponse, JSONResponse
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.branding import PRODUCT_NAME
from app.config import settings
from app.database import get_db
from app.hashing import file_sha256
from app.models import Document, DocumentVersion, Folder, User
from app.permissions import has_permission
from app.security import create_access_token, decode_token
from app.storage import doc_storage_dir

logger = logging.getLogger("newtonedms.wopi")
router = APIRouter(prefix="/wopi", tags=["wopi"])

# In-memory lock registry for active WOPI editing sessions
# Format: {doc_id: {"lock": str, "user_id": int, "username": str, "expires": datetime}}
_wopi_locks: dict[int, dict] = {}


def clean_expired_locks():
    now = datetime.datetime.now(datetime.timezone.utc)
    expired = [doc_id for doc_id, data in _wopi_locks.items() if data.get("expires") and data["expires"] < now]
    for doc_id in expired:
        _wopi_locks.pop(doc_id, None)


def generate_wopi_token(doc_id: int, user_id: int, username: str, can_write: bool = True) -> str:
    """Generate a signed JWT token specifically for a WOPI session with doc_id and permission scopes."""
    ttl = getattr(settings, "wopi_token_ttl_minutes", 1440) or 1440
    data = {
        "sub": username,
        "uid": user_id,
        "doc_id": doc_id,
        "scope": "wopi:write" if can_write else "wopi:read",
        "wopi": True,
    }
    return create_access_token(data, expires=datetime.timedelta(minutes=ttl))


def validate_wopi_token(
    token: Optional[str],
    doc_id: int,
    db: Session,
) -> tuple[User, Document, bool]:
    """Validate a WOPI access token and ensure document access permissions."""
    if not token:
        raise HTTPException(status_code=401, detail="Missing WOPI access token")
    
    try:
        payload = decode_token(token)
    except Exception as exc:
        raise HTTPException(status_code=401, detail=f"Invalid WOPI token: {exc}")
    
    sub = payload.get("sub")
    token_doc_id = payload.get("doc_id")
    scope = payload.get("scope", "wopi:read")
    
    user = db.query(User).filter(User.username == sub).first()
    if not user or not user.is_active:
        raise HTTPException(status_code=401, detail="Invalid user for WOPI token")
    
    doc = db.get(Document, doc_id)
    if not doc or doc.deleted_at is not None:
        raise HTTPException(status_code=404, detail="Document not found or deleted")
    
    if token_doc_id is not None and int(token_doc_id) != doc.id:
        raise HTTPException(status_code=403, detail="Token is not authorized for this document")
    
    folder = db.get(Folder, doc.folder_id) if doc.folder_id else None
    if not has_permission(db, user, "read", folder, doc):
        raise HTTPException(status_code=403, detail="Read permission denied")
    
    can_write = (
        scope == "wopi:write"
        and has_permission(db, user, "write", folder, doc)
        and not bool(doc.locked_by or doc.checked_out_by)
        and not bool(doc.immutable)
    )
    
    return user, doc, can_write


def _get_token_from_request(
    request: Request,
    access_token: Optional[str] = Query(None),
    authorization: Optional[str] = Header(None),
) -> Optional[str]:
    if access_token:
        return access_token
    if authorization and authorization.startswith("Bearer "):
        return authorization[7:].strip()
    return None


@router.get("/files/{file_id}")
async def check_file_info(
    file_id: int,
    request: Request,
    access_token: Optional[str] = Query(None),
    authorization: Optional[str] = Header(None),
    db: Session = Depends(get_db),
):
    """WOPI CheckFileInfo operation.
    
    Returns document metadata, capabilities, permissions, and URLs to the WOPI client.
    """
    token = _get_token_from_request(request, access_token, authorization)
    user, doc, can_write = validate_wopi_token(token, file_id, db)
    
    storage_path = Path(doc.file_path) if doc.file_path else None
    size = storage_path.stat().st_size if (storage_path and storage_path.exists()) else (doc.size or 0)
    
    ver_num = doc.current_version or 1
    version_str = f"{ver_num}.0-" + str(int(doc.updated_at.timestamp() if doc.updated_at else 0))
    file_hash = doc.content_hash or (file_sha256(storage_path) if storage_path and storage_path.exists() else "")
    
    base_url = str(request.base_url).rstrip("/")
    ext = Path(doc.name or "").suffix.lower()
    
    folder = db.get(Folder, doc.folder_id) if doc.folder_id else None
    folder_name = folder.name if folder else "Root"
    
    # Standard WOPI CheckFileInfo JSON Schema
    info = {
        "BaseFileName": doc.name,
        "OwnerId": str(doc.created_by or user.id),
        "Size": size,
        "UserId": str(user.id),
        "UserFriendlyName": getattr(user, "full_name", None) or user.username,
        "Version": version_str,
        "SHA256": file_hash,
        # Capabilities
        "SupportsLocks": True,
        "SupportsGetLock": True,
        "SupportsExtendedLockLength": True,
        "SupportsUpdate": True,
        "SupportsCobalt": False,
        "SupportsFolders": False,
        "SupportsUserInfo": True,
        "SupportsRename": True,
        "SupportsDeleteFile": True,
        # Permissions
        "UserCanWrite": bool(can_write),
        "UserCanReview": bool(can_write),
        "ReadOnly": not bool(can_write),
        "UserCanNotWriteRelative": not bool(can_write),
        # UI / Branding
        "BreadcrumbBrandName": PRODUCT_NAME,
        "BreadcrumbBrandUrl": f"{base_url}/",
        "BreadcrumbDocName": doc.name,
        "BreadcrumbFolderName": folder_name,
        "BreadcrumbFolderUrl": f"{base_url}/#folders/{doc.folder_id}" if doc.folder_id else f"{base_url}/",
        "CloseUrl": f"{base_url}/#doc/{doc.id}",
        "HostEditUrl": f"{base_url}/api/office/wopi/frame/{doc.id}?mode=edit",
        "HostViewUrl": f"{base_url}/api/office/wopi/frame/{doc.id}?mode=view",
        "FileExtension": ext,
        "LastModifiedTime": (doc.updated_at or datetime.datetime.now(datetime.timezone.utc)).isoformat(),
    }
    return JSONResponse(content=info)


@router.get("/files/{file_id}/contents")
async def get_file(
    file_id: int,
    request: Request,
    access_token: Optional[str] = Query(None),
    authorization: Optional[str] = Header(None),
    db: Session = Depends(get_db),
):
    """WOPI GetFile operation.
    
    Streams the raw document content to the WOPI client.
    """
    token = _get_token_from_request(request, access_token, authorization)
    _, doc, _ = validate_wopi_token(token, file_id, db)
    
    if not doc.file_path:
        raise HTTPException(status_code=404, detail="Document file path not set")
    
    file_path = Path(doc.file_path)
    if not file_path.exists():
        raise HTTPException(status_code=404, detail="File on disk not found")
    
    ver_num = doc.current_version or 1
    version_str = f"{ver_num}.0-" + str(int(doc.updated_at.timestamp() if doc.updated_at else 0))
    media_type = doc.mime or "application/octet-stream"
    
    response = FileResponse(
        path=str(file_path),
        media_type=media_type,
        filename=doc.name,
    )
    response.headers["X-WOPI-ItemVersion"] = version_str
    return response


@router.post("/files/{file_id}/contents")
async def put_file(
    file_id: int,
    request: Request,
    access_token: Optional[str] = Query(None),
    authorization: Optional[str] = Header(None),
    x_wopi_lock: Optional[str] = Header(None, alias="X-WOPI-Lock"),
    x_wopi_override: Optional[str] = Header(None, alias="X-WOPI-Override"),
    db: Session = Depends(get_db),
):
    """WOPI PutFile operation.
    
    Saves an updated document revision from the WOPI editor back into NewtonEDMS.
    """
    clean_expired_locks()
    token = _get_token_from_request(request, access_token, authorization)
    user, doc, can_write = validate_wopi_token(token, file_id, db)
    
    if not can_write:
        raise HTTPException(status_code=403, detail="Write permission denied")
    
    # Check lock if locked
    active_lock = _wopi_locks.get(doc.id)
    if active_lock:
        if not x_wopi_lock or active_lock.get("lock") != x_wopi_lock:
            # Conflict
            return Response(
                status_code=409,
                headers={"X-WOPI-Lock": active_lock.get("lock", "")},
            )
    
    body = await request.body()
    if not body:
        raise HTTPException(status_code=400, detail="Empty request body for PutFile")
    
    dest_dir = doc_storage_dir(doc.id)
    dest_dir.mkdir(parents=True, exist_ok=True)
    
    # Current version number
    old_version = doc.current_version or 1
    new_version = old_version + 1
    
    # Archive existing file if present
    curr_path = Path(doc.file_path) if doc.file_path else None
    if curr_path and curr_path.exists():
        archive_name = f"v_{old_version}_{doc.name}"
        archive_path = dest_dir / archive_name
        try:
            shutil.copy2(curr_path, archive_path)
            ver_row = DocumentVersion(
                document_id=doc.id,
                version_number=old_version,
                file_path=str(archive_path),
                size=curr_path.stat().st_size,
                created_by=user.id,
                comment=f"Saved via Microsoft Office Online ({user.username})",
            )
            db.add(ver_row)
        except Exception as exc:
            logger.warning("Could not archive version: %s", exc)
    
    # Write new file content
    ext = Path(doc.name or "").suffix
    target_file = dest_dir / f"content{ext}"
    target_file.write_bytes(body)
    
    new_hash = hashlib.sha256(body).hexdigest()
    doc.file_path = str(target_file)
    doc.size = len(body)
    doc.content_hash = new_hash
    doc.current_version = new_version
    doc.updated_at = datetime.datetime.now(datetime.timezone.utc)
    
    db.commit()
    db.refresh(doc)
    
    # Trigger background re-indexing if available
    try:
        from app.indexing import index_document
        index_document(doc.id)
    except Exception as exc:
        logger.debug("Indexing triggered: %s", exc)
    
    version_str = f"{doc.current_version}.0-" + str(int(doc.updated_at.timestamp()))
    return JSONResponse(
        content={"ItemVersion": version_str},
        headers={"X-WOPI-ItemVersion": version_str},
    )


@router.post("/files/{file_id}")
async def wopi_override_dispatch(
    file_id: int,
    request: Request,
    access_token: Optional[str] = Query(None),
    authorization: Optional[str] = Header(None),
    x_wopi_override: Optional[str] = Header(None, alias="X-WOPI-Override"),
    x_wopi_lock: Optional[str] = Header(None, alias="X-WOPI-Lock"),
    x_wopi_old_lock: Optional[str] = Header(None, alias="X-WOPI-OldLock"),
    x_wopi_requested_name: Optional[str] = Header(None, alias="X-WOPI-RequestedName"),
    x_wopi_suggested_target: Optional[str] = Header(None, alias="X-WOPI-SuggestedTarget"),
    x_wopi_relative_target: Optional[str] = Header(None, alias="X-WOPI-RelativeTarget"),
    db: Session = Depends(get_db),
):
    """WOPI Operations dispatcher based on X-WOPI-Override header.
    
    Supports: LOCK, GET_LOCK, REFRESH_LOCK, UNLOCK, PUT_RELATIVE, RENAME_FILE, DELETE.
    """
    clean_expired_locks()
    token = _get_token_from_request(request, access_token, authorization)
    user, doc, can_write = validate_wopi_token(token, file_id, db)
    
    override = (x_wopi_override or "").upper()
    ver_num = doc.current_version or 1
    version_str = f"{ver_num}.0-" + str(int(doc.updated_at.timestamp() if doc.updated_at else 0))
    active_lock = _wopi_locks.get(doc.id)
    
    # 1. LOCK
    if override == "LOCK":
        if not can_write:
            raise HTTPException(status_code=403, detail="Write permission required to lock")
        if not x_wopi_lock:
            raise HTTPException(status_code=400, detail="Missing X-WOPI-Lock header")
        
        # If unlocked or lock matches old lock
        if not active_lock or (x_wopi_old_lock and active_lock.get("lock") == x_wopi_old_lock) or (active_lock.get("lock") == x_wopi_lock):
            _wopi_locks[doc.id] = {
                "lock": x_wopi_lock,
                "user_id": user.id,
                "username": user.username,
                "expires": datetime.datetime.now(datetime.timezone.utc) + datetime.timedelta(minutes=30),
            }
            return Response(
                status_code=200,
                headers={"X-WOPI-ItemVersion": version_str},
            )
        else:
            # Conflict: return current lock
            return Response(
                status_code=409,
                headers={
                    "X-WOPI-Lock": active_lock.get("lock", ""),
                    "X-WOPI-LockFailureReason": "File is already locked by another session",
                },
            )
    
    # 2. GET_LOCK
    elif override == "GET_LOCK":
        lock_val = active_lock.get("lock", "") if active_lock else ""
        return Response(
            status_code=200,
            headers={"X-WOPI-Lock": lock_val},
        )
    
    # 3. REFRESH_LOCK
    elif override == "REFRESH_LOCK":
        if not active_lock:
            return Response(
                status_code=409,
                headers={"X-WOPI-Lock": "", "X-WOPI-LockFailureReason": "File is not locked"},
            )
        if active_lock.get("lock") != x_wopi_lock:
            return Response(
                status_code=409,
                headers={"X-WOPI-Lock": active_lock.get("lock", ""), "X-WOPI-LockFailureReason": "Lock mismatch"},
            )
        
        # Extend lock
        active_lock["expires"] = datetime.datetime.now(datetime.timezone.utc) + datetime.timedelta(minutes=30)
        return Response(
            status_code=200,
            headers={"X-WOPI-ItemVersion": version_str},
        )
    
    # 4. UNLOCK
    elif override == "UNLOCK":
        if not active_lock:
            return Response(
                status_code=409,
                headers={"X-WOPI-Lock": "", "X-WOPI-LockFailureReason": "File is not locked"},
            )
        if active_lock.get("lock") != x_wopi_lock:
            return Response(
                status_code=409,
                headers={"X-WOPI-Lock": active_lock.get("lock", ""), "X-WOPI-LockFailureReason": "Lock mismatch"},
            )
        
        _wopi_locks.pop(doc.id, None)
        return Response(
            status_code=200,
            headers={"X-WOPI-ItemVersion": version_str},
        )
    
    # 5. RENAME_FILE
    elif override == "RENAME_FILE":
        if not can_write:
            raise HTTPException(status_code=403, detail="Permission denied")
        if not x_wopi_requested_name:
            raise HTTPException(status_code=400, detail="Missing X-WOPI-RequestedName header")
        
        doc.name = x_wopi_requested_name.strip()
        doc.updated_at = datetime.datetime.now(datetime.timezone.utc)
        db.commit()
        return JSONResponse(content={"Name": doc.name})
    
    # 6. DELETE
    elif override == "DELETE":
        if not can_write:
            raise HTTPException(status_code=403, detail="Permission denied")
        doc.deleted_at = datetime.datetime.now(datetime.timezone.utc)
        db.commit()
        return Response(status_code=200)
    
    # 7. PUT_RELATIVE
    elif override == "PUT_RELATIVE":
        if not can_write:
            raise HTTPException(status_code=403, detail="Permission denied")
        
        body = await request.body()
        name = x_wopi_relative_target or x_wopi_suggested_target or f"Copy_of_{doc.name}"
        if name.startswith("."):
            name = f"{Path(doc.name).stem}_copy{name}"
        
        new_doc = Document(
            folder_id=doc.folder_id,
            name=name,
            title=name,
            mime=doc.mime or "application/octet-stream",
            file_path="",
            created_by=user.id,
            size=len(body) if body else 0,
            current_version=1,
        )
        db.add(new_doc)
        db.commit()
        db.refresh(new_doc)
        
        if body:
            target_dir = doc_storage_dir(new_doc.id)
            target_dir.mkdir(parents=True, exist_ok=True)
            target_file = target_dir / f"content{Path(name).suffix}"
            target_file.write_bytes(body)
            new_doc.file_path = str(target_file)
            new_doc.content_hash = hashlib.sha256(body).hexdigest()
            db.commit()
        
        base_url = str(request.base_url).rstrip("/")
        new_token = generate_wopi_token(new_doc.id, user.id, user.username, can_write=True)
        return JSONResponse(
            content={
                "Name": new_doc.name,
                "Url": f"{base_url}/wopi/files/{new_doc.id}?access_token={new_token}",
                "HostEditUrl": f"{base_url}/api/office/wopi/frame/{new_doc.id}?mode=edit",
                "HostViewUrl": f"{base_url}/api/office/wopi/frame/{new_doc.id}?mode=view",
            }
        )
    
    else:
        raise HTTPException(status_code=400, detail=f"Unsupported X-WOPI-Override: {x_wopi_override}")
