"""Document, versioning, check-out, and download routes."""

import json
import mimetypes
import shutil
import uuid
from pathlib import Path

from fastapi import APIRouter, Depends, File, Form, HTTPException, Query, Request, UploadFile
from fastapi.responses import FileResponse
from pydantic import BaseModel
from sqlalchemy import String, cast, or_
from sqlalchemy.orm import Session

from app import database
from app.audit import audit
from app.database import get_db, now
from app.indexing import index_document, remove_document, search_documents
from app.joex import schedule_document
from app.models import (
    CalendarEvent,
    Comment,
    CustomFieldValue,
    Document,
    DocumentAttachment,
    DocumentVersion,
    Folder,
    MetadataTemplate,
    ProcessingJob,
    ShareLink,
    Task,
    User,
    WorkflowInstance,
)
from app.permissions import has_permission, readable_document_ids, readable_folder_ids
from app.querylang import apply_filters, parse_query
from app.schemas import DocumentOut, VersionOut
from app.security import get_current_user
from app.storage import doc_storage_dir, safe_filename, save_upload, validate_upload_filename

router = APIRouter(prefix="/api/documents", tags=["documents"])


def _parse_dt(value: str):
    if not value:
        return None
    from datetime import datetime

    for fmt in ("%Y-%m-%d", "%Y-%m-%dT%H:%M", "%Y-%m-%dT%H:%M:%S"):
        try:
            return datetime.strptime(value, fmt)
        except ValueError:
            continue
    raise HTTPException(status_code=400, detail=f"Invalid date: {value}")


@router.get("", response_model=list[DocumentOut])
def list_documents(
    folder_id: int | None = Query(None),
    search: str | None = Query(None),
    tags: str | None = Query(None),
    status: str | None = Query(None),
    skip: int = Query(0, ge=0),
    limit: int = Query(100, le=500),
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    q = db.query(Document).filter(Document.deleted_at.is_(None))
    if folder_id is not None:
        q = q.filter(Document.folder_id == folder_id)
    if search:
        parsed = parse_query(search)
        q = apply_filters(q, parsed, db)
        text = parsed.fulltext or (search if ":" not in search else "")
        if text:
            like = f"%{text}%"
            full_text_ids = search_documents(text, limit=1000)
            text_conditions = [
                (Document.name.ilike(like))
                | (Document.title.ilike(like))
                | (Document.tags.ilike(like))
                | (cast(Document.metadata_json, String).ilike(like))
                | (Document.notes.ilike(like))
                | (Document.extracted_text.ilike(like))
            ]
            if full_text_ids:
                text_conditions.append(Document.id.in_(full_text_ids))
            q = q.filter(or_(*text_conditions))
    if tags:
        for tag in tags.split(","):
            q = q.filter(Document.tags.ilike(f"%{tag.strip()}%"))
    if status:
        q = q.filter(Document.status == status)
    if user.role not in ("superadmin", "admin"):
        # Push visibility into SQL so we don't issue a permission query per document.
        conditions = [Document.created_by == user.id]
        folders = readable_folder_ids(db, user)
        if folders:
            conditions.append(Document.folder_id.in_(folders))
        docs = readable_document_ids(db, user)
        if docs:
            conditions.append(Document.id.in_(docs))
        q = q.filter(or_(*conditions))
    from app.tenancy import filter_documents

    q = filter_documents(q, user)
    q = q.order_by(Document.updated_at.desc()).offset(skip).limit(limit)
    return q.all()


@router.get("/{doc_id}", response_model=DocumentOut)
def get_document(
    doc_id: int,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    d = db.get(Document, doc_id)
    if not d or d.deleted_at:
        raise HTTPException(status_code=404, detail="Document not found")
    f = db.get(Folder, d.folder_id)
    if not has_permission(db, user, "read", f, d):
        audit(
            db,
            user,
            "DOCUMENT_ACCESS_DENIED",
            "document",
            d.id,
            f"Unauthorized read attempt on document '{d.title or d.name}'",
            resource_name=d.title or d.name,
            severity="HIGH",
            status="DENIED",
        )
        raise HTTPException(status_code=403, detail="No permission")
    audit(
        db,
        user,
        "DOCUMENT_VIEW",
        "document",
        d.id,
        f"Viewed document '{d.title or d.name}'",
        resource_name=d.title or d.name,
        severity="INFO",
        status="SUCCESS",
    )
    return d


def _upload_one(
    db: Session,
    user: User,
    folder: Folder,
    file: UploadFile,
    title: str | None = None,
    tags: str = "",
    metadata: dict | None = None,
    template_id: int | None = None,
    skip_duplicates: bool = False,
    source_id: int | None = None,
) -> Document:
    meta = metadata or {}
    if template_id is not None:
        tpl = db.get(MetadataTemplate, template_id)
        if not tpl:
            raise HTTPException(status_code=404, detail="Metadata template not found")
        defaults = {f.get("key"): f.get("default") for f in (tpl.fields or []) if "key" in f}
        meta = {**defaults, **meta}
    name = safe_filename(file.filename)
    validate_upload_filename(name)
    tmp_path = database.STORAGE_DIR / f".upload_{uuid.uuid4().hex}"
    used = 0
    if user.quota_bytes:
        from sqlalchemy import func as sqlfunc

        used = (
            db.query(sqlfunc.coalesce(sqlfunc.sum(Document.size), 0))
            .filter(Document.created_by == user.id, Document.deleted_at.is_(None))
            .scalar()
            or 0
        )
    try:
        size = save_upload(file.file, tmp_path)
        if user.quota_bytes and used + size > user.quota_bytes:
            tmp_path.unlink(missing_ok=True)
            raise HTTPException(status_code=413, detail="Storage quota exceeded")
        from app.hashing import file_sha256

        digest = file_sha256(tmp_path)
        if skip_duplicates:
            twin = db.query(Document).filter(Document.content_hash == digest, Document.deleted_at.is_(None)).first()
            if twin:
                tmp_path.unlink(missing_ok=True)
                raise HTTPException(status_code=409, detail=f"Duplicate of document {twin.id}")
        d = Document(
            name=name,
            title=title or name,
            folder_id=folder.id,
            tags=tags,
            metadata_json=meta,
            created_by=user.id,
            size=size,
            mime=file.content_type or mimetypes.guess_type(name)[0] or "application/octet-stream",
            file_path=str(tmp_path),
            content_hash=digest,
            source_id=source_id,
            confirmed=False,
            collective_id=getattr(folder, "collective_id", None) or user.collective_id,
        )
        db.add(d)
        db.flush()
        dest_dir = doc_storage_dir(d.id)
        ext = Path(name).suffix
        dest = dest_dir / f"v1{ext}"
        shutil.move(str(tmp_path), str(dest))
        d.file_path = str(dest)
        d.size = dest.stat().st_size
        try:
            from app.backends import persist

            loc = persist(db, f"doc_{d.id}", dest, d.mime)
            if loc and loc != str(dest):
                d.file_path = loc
        except Exception:
            pass
        v = DocumentVersion(
            document_id=d.id,
            version_number=1,
            file_path=str(dest),
            size=d.size,
            created_by=user.id,
            comment="Initial upload",
        )
        db.add(v)
        db.commit()
    except Exception:
        db.rollback()
        tmp_path.unlink(missing_ok=True)
        raise
    index_document(d.id, d.title, d.tags, d.file_path, d.size)
    schedule_document(db, d.id, created_by=user.id)
    try:
        from app.hooks import after_document_create

        after_document_create(db, d)
    except Exception:
        pass
    audit(db, user, "DOCUMENT_CREATE", "document", d.id, f"Uploaded {name} to folder {folder.id}")
    return d


@router.post("", response_model=DocumentOut)
def upload_document(
    folder_id: int = Form(...),
    title: str | None = Form(None),
    tags: str | None = Form(""),
    metadata: str | None = Form("{}"),
    template_id: int | None = Form(None),
    skip_duplicates: bool = Form(False),
    source_id: int | None = Form(None),
    file: UploadFile = File(...),
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    f = db.get(Folder, folder_id)
    if not f:
        raise HTTPException(status_code=404, detail="Folder not found")
    if not has_permission(db, user, "write", f):
        raise HTTPException(status_code=403, detail="No permission to upload")
    try:
        meta = json.loads(metadata or "{}")
    except Exception:
        raise HTTPException(status_code=400, detail="Invalid metadata JSON") from None
    return _upload_one(
        db, user, f, file, title=title, tags=tags, metadata=meta, template_id=template_id,
        skip_duplicates=skip_duplicates, source_id=source_id,
    )


@router.post("/bulk", response_model=list[DocumentOut])
def bulk_upload(
    folder_id: int = Form(...),
    tags: str | None = Form(""),
    metadata: str | None = Form("{}"),
    template_id: int | None = Form(None),
    files: list[UploadFile] = File(...),
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    f = db.get(Folder, folder_id)
    if not f:
        raise HTTPException(status_code=404, detail="Folder not found")
    if not has_permission(db, user, "write", f):
        raise HTTPException(status_code=403, detail="No permission to upload")
    try:
        meta = json.loads(metadata or "{}")
    except Exception:
        raise HTTPException(status_code=400, detail="Invalid metadata JSON") from None
    results = []
    for file in files:
        try:
            d = _upload_one(db, user, f, file, tags=tags, metadata=meta, template_id=template_id, skip_duplicates=False)
            results.append(d)
        except HTTPException:
            raise
        except Exception as exc:
            audit(db, user, "BULK_UPLOAD_ERROR", "document", None, f"{file.filename}: {exc}")
    return results


@router.get("/{doc_id}/download")
def download_document(
    doc_id: int,
    version: int | None = Query(None, ge=1, alias="v"),
    db: Session = Depends(get_db),
    request: Request = None,
    user: User = Depends(get_current_user),
):
    d = db.get(Document, doc_id)
    if not d:
        raise HTTPException(status_code=404, detail="Document not found")
    f = db.get(Folder, d.folder_id)
    if not has_permission(db, user, "read", f, d):
        raise HTTPException(status_code=403, detail="No permission")
    if version is None:
        path = Path(d.file_path)
        download_name = d.name
    else:
        v = (
            db.query(DocumentVersion)
            .filter(
                DocumentVersion.document_id == doc_id,
                DocumentVersion.version_number == version,
            )
            .first()
        )
        if not v:
            raise HTTPException(status_code=404, detail="Version not found")
        path = Path(v.file_path)
        stem = Path(d.name).stem
        ext = Path(d.name).suffix
        download_name = f"{stem}-v{version}{ext}"
    if not path.exists():
        raise HTTPException(status_code=404, detail="File not found on disk")
    audit(
        db, user, "DOCUMENT_DOWNLOAD", "document", d.id, f"Downloaded {download_name}",
        ip=request.client.host if request else None,
    )
    return FileResponse(path, filename=download_name, media_type=d.mime)


@router.get("/{doc_id}/versions", response_model=list[VersionOut])
def list_versions(
    doc_id: int,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    d = db.get(Document, doc_id)
    if not d:
        raise HTTPException(status_code=404, detail="Document not found")
    f = db.get(Folder, d.folder_id)
    if not has_permission(db, user, "read", f, d):
        raise HTTPException(status_code=403, detail="No permission")
    return (
        db.query(DocumentVersion)
        .filter(DocumentVersion.document_id == doc_id)
        .order_by(DocumentVersion.version_number.desc())
        .all()
    )


@router.post("/{doc_id}/versions", response_model=DocumentOut)
def add_version(
    doc_id: int,
    comment: str | None = Form(""),
    file: UploadFile = File(...),
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    d = db.get(Document, doc_id)
    if not d:
        raise HTTPException(status_code=404, detail="Document not found")
    f = db.get(Folder, d.folder_id)
    if not has_permission(db, user, "write", f, d):
        raise HTTPException(status_code=403, detail="No permission to add version")
    if d.checked_out_by and d.checked_out_by != user.id and user.role not in ("superadmin", "admin"):
        raise HTTPException(status_code=403, detail="Document is checked out by another user")
    validate_upload_filename(safe_filename(file.filename))
    new_version = d.current_version + 1
    ext = Path(d.name).suffix
    dest = doc_storage_dir(d.id) / f"v{new_version}{ext}"
    size = save_upload(file.file, dest)
    v = DocumentVersion(
        document_id=d.id,
        version_number=new_version,
        file_path=str(dest),
        size=size,
        created_by=user.id,
        comment=comment,
    )
    db.add(v)
    d.current_version = new_version
    d.file_path = str(dest)
    d.size = size
    d.mime = file.content_type or d.mime
    d.updated_at = now()
    db.commit()
    index_document(d.id, d.title, d.tags, d.file_path, d.size)
    audit(db, user, "VERSION_CREATE", "document", d.id, f"Version {new_version} added: {comment}")
    return d


@router.post("/{doc_id}/restore/{version_number}")
def restore_version(
    doc_id: int,
    version_number: int,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    d = db.get(Document, doc_id)
    if not d:
        raise HTTPException(status_code=404, detail="Document not found")
    f = db.get(Folder, d.folder_id)
    if not has_permission(db, user, "write", f, d):
        raise HTTPException(status_code=403, detail="No permission")
    v = (
        db.query(DocumentVersion)
        .filter(
            DocumentVersion.document_id == doc_id,
            DocumentVersion.version_number == version_number,
        )
        .first()
    )
    if not v:
        raise HTTPException(status_code=404, detail="Version not found")
    src = Path(v.file_path)
    if not src.exists():
        raise HTTPException(status_code=404, detail="Version file missing")
    new_version = d.current_version + 1
    ext = Path(d.name).suffix
    dest = doc_storage_dir(d.id) / f"v{new_version}{ext}"
    shutil.copy2(src, dest)
    nv = DocumentVersion(
        document_id=d.id,
        version_number=new_version,
        file_path=str(dest),
        size=dest.stat().st_size,
        created_by=user.id,
        comment=f"Restored from version {version_number}",
    )
    db.add(nv)
    d.current_version = new_version
    d.file_path = str(dest)
    d.size = dest.stat().st_size
    d.updated_at = now()
    db.commit()
    index_document(d.id, d.title, d.tags, d.file_path, d.size)
    audit(db, user, "VERSION_RESTORE", "document", d.id, f"Restored version {version_number} as {new_version}")
    return {"ok": True, "new_version": new_version}


@router.post("/{doc_id}/checkout")
def checkout_document(
    doc_id: int,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    d = db.get(Document, doc_id)
    if not d:
        raise HTTPException(status_code=404, detail="Document not found")
    f = db.get(Folder, d.folder_id)
    if not has_permission(db, user, "write", f, d):
        raise HTTPException(status_code=403, detail="No permission")
    if d.checked_out_by:
        raise HTTPException(status_code=400, detail=f"Already checked out by user {d.checked_out_by}")
    d.checked_out_by = user.id
    db.commit()
    audit(db, user, "DOCUMENT_CHECKOUT", "document", d.id, "Checked out")
    return {"ok": True}


@router.post("/{doc_id}/checkin")
def checkin_document(
    doc_id: int,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    d = db.get(Document, doc_id)
    if not d:
        raise HTTPException(status_code=404, detail="Document not found")
    f = db.get(Folder, d.folder_id)
    if not has_permission(db, user, "write", f, d):
        raise HTTPException(status_code=403, detail="No permission")
    if d.checked_out_by and d.checked_out_by != user.id and user.role not in ("superadmin", "admin"):
        raise HTTPException(status_code=403, detail="Document checked out by another user")
    d.checked_out_by = None
    db.commit()
    audit(db, user, "DOCUMENT_CHECKIN", "document", d.id, "Checked in")
    return {"ok": True}


class OwnerIn(BaseModel):
    user_id: int


@router.post("/{doc_id}/owner", response_model=DocumentOut)
def transfer_ownership(
    doc_id: int,
    payload: OwnerIn,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    d = db.get(Document, doc_id)
    if not d:
        raise HTTPException(status_code=404, detail="Document not found")
    if d.deleted_at:
        raise HTTPException(status_code=404, detail="Document not found")
    if d.created_by != user.id and user.role not in ("superadmin", "admin"):
        raise HTTPException(status_code=403, detail="Only the owner or an admin can transfer ownership")
    target = db.get(User, payload.user_id)
    if not target or not target.is_active:
        raise HTTPException(status_code=404, detail="Target user not found or inactive")
    if target.id == d.created_by:
        raise HTTPException(status_code=400, detail="User already owns this document")
    old_owner = d.created_by
    d.created_by = target.id
    # The new owner takes over an open checkout so it cannot orphan the lock.
    if d.checked_out_by == old_owner:
        d.checked_out_by = target.id
    db.commit()
    db.refresh(d)
    audit(db, user, "DOCUMENT_TRANSFER_OWNER", "document", d.id, f"Ownership {old_owner} -> {target.id}")
    return d


@router.put("/{doc_id}", response_model=DocumentOut)
def update_document(
    doc_id: int,
    title: str | None = Form(None),
    tags: str | None = Form(None),
    metadata: str | None = Form(None),
    status: str | None = Form(None),
    notes: str | None = Form(None),
    correspondent_id: int | None = Form(None),
    concerning_id: int | None = Form(None),
    due_date: str | None = Form(None),
    item_date: str | None = Form(None),
    direction: str | None = Form(None),
    equipment: str | None = Form(None),
    custom_id: str | None = Form(None),
    language: str | None = Form(None),
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    d = db.get(Document, doc_id)
    if not d:
        raise HTTPException(status_code=404, detail="Document not found")
    f = db.get(Folder, d.folder_id)
    if not has_permission(db, user, "write", f, d):
        raise HTTPException(status_code=403, detail="No permission")
    if getattr(d, "immutable", False):
        raise HTTPException(status_code=400, detail="Document is immutable")
    if getattr(d, "locked_by", None) and d.locked_by != user.id and user.role not in ("admin", "superadmin"):
        raise HTTPException(status_code=403, detail="Document is locked")
    if title is not None:
        d.title = title
    if tags is not None:
        d.tags = tags
    if metadata is not None:
        try:
            d.metadata_json = json.loads(metadata)
        except Exception:
            raise HTTPException(status_code=400, detail="Invalid metadata JSON") from None
    if status is not None:
        allowed = {
            "draft": ["review", "approved", "archived"],
            "review": ["draft", "approved"],
            "approved": ["published", "draft"],
            "published": ["archived", "draft"],
            "archived": ["draft"],
        }
        if status not in allowed.get(d.status, []) and user.role not in ("superadmin", "admin"):
            raise HTTPException(status_code=400, detail="Invalid workflow transition")
        d.status = status
    if notes is not None:
        d.notes = notes
    if correspondent_id is not None:
        d.correspondent_id = correspondent_id or None
    if concerning_id is not None:
        d.concerning_id = concerning_id or None
    if due_date is not None:
        d.due_date = _parse_dt(due_date)
    if item_date is not None:
        d.item_date = _parse_dt(item_date)
    if direction is not None:
        d.direction = direction
    if equipment is not None:
        d.equipment = equipment
    if custom_id is not None:
        d.custom_id = custom_id
    if language is not None:
        d.language = language
    d.updated_at = now()
    db.commit()
    db.refresh(d)
    index_document(d.id, d.title, d.tags, d.file_path, d.size)
    audit(db, user, "DOCUMENT_UPDATE", "document", d.id, "Updated metadata/status")
    return d


@router.delete("/{doc_id}")
def delete_document(
    doc_id: int,
    permanent: bool = Query(False),
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    d = db.get(Document, doc_id)
    if not d:
        raise HTTPException(status_code=404, detail="Document not found")
    f = db.get(Folder, d.folder_id)
    if not has_permission(db, user, "delete", f, d):
        raise HTTPException(status_code=403, detail="No permission")
    from app.compliance import is_held

    if is_held(db, d):
        raise HTTPException(status_code=423, detail="Document is on legal hold")
    if d.immutable and not permanent:
        raise HTTPException(status_code=400, detail="Document is immutable")
    if not permanent:
        d.deleted_at = now()
        d.deleted_by = user.id
        db.commit()
        audit(db, user, "DOCUMENT_TRASH", "document", doc_id, f"Trashed {d.name}")
        return {"ok": True, "trashed": True}
    ddir = doc_storage_dir(d.id)
    if ddir.exists():
        shutil.rmtree(ddir)
    remove_document(doc_id)
    from app.purge import purge_document_children

    purge_document_children(db, doc_id)
    db.delete(d)
    db.commit()
    audit(db, user, "DOCUMENT_DELETE", "document", doc_id, f"Deleted document {d.name}")
    return {"ok": True}
