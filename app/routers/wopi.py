"""WOPI host for Microsoft Office Online / OnlyOffice editing."""
from __future__ import annotations

import urllib.parse
from datetime import timedelta
from io import BytesIO
from pathlib import Path
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import FileResponse, Response
from sqlalchemy.orm import Session

from app.audit import audit
from app.config import settings
from app.database import get_db, now
from app.indexing import index_document
from app.models import Document, DocumentVersion, Folder, User
from app.permissions import has_permission
from app.security import create_access_token, decode_token, get_current_user
from app.storage import doc_storage_dir, save_upload, validate_upload_filename

router = APIRouter(prefix="/api/wopi", tags=["wopi"])

_OFFICE_KINDS = {
    "word": [
        "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
        "application/msword",
    ],
    "excel": [
        "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        "application/vnd.ms-excel",
    ],
    "ppt": [
        "application/vnd.openxmlformats-officedocument.presentationml.presentation",
        "application/vnd.ms-powerpoint",
    ],
}


def _office_kind(mime: str | None) -> Optional[str]:
    if not mime:
        return None
    for kind, mimes in _OFFICE_KINDS.items():
        if mime in mimes:
            return kind
    return None


def _wopi_public_src(request: Request, doc_id: int) -> str:
    base = str(request.base_url).rstrip("/")
    return f"{base}/api/wopi/files/{doc_id}"


def _wopi_token_user(request: Request, db: Session) -> tuple[User, dict]:
    token = request.query_params.get("access_token")
    if not token:
        raise HTTPException(status_code=401, detail="Missing access_token")
    payload = decode_token(token)
    if not payload or payload.get("wopi_doc_id") is None:
        raise HTTPException(status_code=401, detail="Invalid WOPI token")
    user = (
        db.query(User)
        .filter(User.username == payload.get("sub"), User.is_active == True)
        .first()
    )
    if not user:
        raise HTTPException(status_code=401, detail="User not found")
    return user, payload


def _version_string(d: Document) -> str:
    return f"v{d.current_version}-{d.updated_at.isoformat()}" if d.updated_at else f"v{d.current_version}"


@router.get("/session/{doc_id}")
def wopi_session(
    doc_id: int,
    request: Request,
    mode: str = "edit",
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    d = db.get(Document, doc_id)
    if not d:
        raise HTTPException(status_code=404, detail="Document not found")
    f = db.get(Folder, d.folder_id)
    if not has_permission(db, user, "read", f, d):
        raise HTTPException(status_code=403, detail="No permission")
    kind = _office_kind(d.mime)
    if not kind:
        raise HTTPException(status_code=400, detail="Not an Office document")
    can_edit = (
        mode == "edit"
        and has_permission(db, user, "write", f, d)
        and (not d.checked_out_by or d.checked_out_by == user.id)
    )
    token = create_access_token(
        {
            "sub": user.username,
            "wopi_doc_id": d.id,
            "wopi_can_edit": can_edit,
        },
        expires=timedelta(minutes=30),
    )
    wopi_src = _wopi_public_src(request, d.id)
    wopi_src_with_token = f"{wopi_src}?access_token={urllib.parse.quote(token, safe='')}"

    verb = "ofe" if can_edit else "ofv"
    desktop = f"ms-{kind}:{verb}%7Cu%7C{urllib.parse.quote(wopi_src_with_token, safe='')}"  # type: ignore[assignment]

    online_url = None
    if settings.office_online_url:
        qs = urllib.parse.urlencode(
            {"WOPISrc": wopi_src, "access_token": token},
            quote_via=urllib.parse.quote,
        )
        online_url = f"{settings.office_online_url}?{qs}"

    return {
        "doc_id": d.id,
        "kind": kind,
        "wopi_src": wopi_src,
        "access_token": token,
        "can_edit": can_edit,
        "online_url": online_url,
        "desktop_url": desktop,
    }


@router.get("/files/{doc_id}")
def wopi_check_file_info(
    request: Request,
    doc_id: int,
    db: Session = Depends(get_db),
):
    user, payload = _wopi_token_user(request, db)
    if payload.get("wopi_doc_id") != doc_id:
        raise HTTPException(status_code=401, detail="Token mismatch")
    d = db.get(Document, doc_id)
    if not d:
        raise HTTPException(status_code=404, detail="Document not found")
    f = db.get(Folder, d.folder_id)
    if not has_permission(db, user, "read", f, d):
        raise HTTPException(status_code=403, detail="No permission")
    can_edit = payload.get("wopi_can_edit", False) and not d.checked_out_by
    if d.checked_out_by and d.checked_out_by != user.id:
        can_edit = False
    return {
        "BaseFileName": d.name,
        "FileName": d.name,
        "BreadcrumbDocName": d.title or d.name,
        "Size": d.size,
        "Version": _version_string(d),
        "OwnerId": str(d.created_by),
        "UserId": str(user.id),
        "UserFriendlyName": user.username,
        "ReadOnly": not can_edit,
        "UserCanWrite": can_edit,
        "UserCanNotWriteRelative": True,
        "SupportsUpdate": can_edit,
        "SupportsLocks": False,
        "SupportsGetLock": False,
        "SupportsExtendedLockLength": False,
        "SupportsCobalt": False,
        "LastModifiedTime": d.updated_at.isoformat() if d.updated_at else now().isoformat(),
        "LicenseCheckForEditIsEnabled": False,
    }


@router.get("/files/{doc_id}/contents")
def wopi_get_contents(
    request: Request,
    doc_id: int,
    db: Session = Depends(get_db),
):
    user, payload = _wopi_token_user(request, db)
    if payload.get("wopi_doc_id") != doc_id:
        raise HTTPException(status_code=401, detail="Token mismatch")
    d = db.get(Document, doc_id)
    if not d:
        raise HTTPException(status_code=404, detail="Document not found")
    f = db.get(Folder, d.folder_id)
    if not has_permission(db, user, "read", f, d):
        raise HTTPException(status_code=403, detail="No permission")
    path = Path(d.file_path)
    if not path.exists():
        raise HTTPException(status_code=404, detail="File missing")
    return FileResponse(
        path,
        filename=d.name,
        media_type=d.mime or "application/octet-stream",
        headers={"X-WOPI-ItemVersion": _version_string(d)},
    )


@router.post("/files/{doc_id}/contents")
async def wopi_put_contents(
    request: Request,
    doc_id: int,
    db: Session = Depends(get_db),
):
    user, payload = _wopi_token_user(request, db)
    if payload.get("wopi_doc_id") != doc_id:
        raise HTTPException(status_code=401, detail="Token mismatch")
    if not payload.get("wopi_can_edit"):
        raise HTTPException(status_code=403, detail="Read-only token")
    d = db.get(Document, doc_id)
    if not d:
        raise HTTPException(status_code=404, detail="Document not found")
    f = db.get(Folder, d.folder_id)
    if not has_permission(db, user, "write", f, d):
        raise HTTPException(status_code=403, detail="No permission")
    if d.checked_out_by and d.checked_out_by != user.id:
        raise HTTPException(status_code=403, detail="Checked out by another user")

    body = await request.body()
    if not body:
        raise HTTPException(status_code=400, detail="Empty body")

    validate_upload_filename(d.name)
    new_version = d.current_version + 1
    ext = Path(d.name).suffix
    dest = doc_storage_dir(d.id) / f"v{new_version}{ext}"
    size = save_upload(BytesIO(body), dest)

    v = DocumentVersion(
        document_id=d.id,
        version_number=new_version,
        file_path=str(dest),
        size=size,
        created_by=user.id,
        comment="WOPI save",
    )
    db.add(v)
    d.current_version = new_version
    d.file_path = str(dest)
    d.size = size
    d.updated_at = now()
    d.mime = d.mime or "application/octet-stream"
    db.commit()
    index_document(d.id, d.title, d.tags, d.file_path, d.size)
    audit(db, user, "WOPI_SAVE", "document", d.id, f"Version {new_version}")
    return Response(status_code=200)
