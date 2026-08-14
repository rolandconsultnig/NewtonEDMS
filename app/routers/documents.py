"""Document, versioning, check-out, and download routes."""

import json
import mimetypes
import shutil
import uuid
from pathlib import Path
from typing import Optional

from fastapi import APIRouter, Depends, File, Form, HTTPException, Query, Request, UploadFile, status
from fastapi.responses import FileResponse
from sqlalchemy import String, cast, or_
from sqlalchemy.orm import Session

from app import database
from app.audit import audit
from app.database import get_db, now
from app.indexing import index_document, remove_document, search_documents
from app.models import (
    CalendarEvent,
    Comment,
    Document,
    DocumentVersion,
    Folder,
    MetadataTemplate,
    ShareLink,
    Task,
    User,
    WorkflowInstance,
)
from app.permissions import has_permission, readable_document_ids, readable_folder_ids
from app.schemas import DocumentOut, VersionOut
from app.security import get_current_user
from app.storage import doc_storage_dir, safe_filename, save_upload, validate_upload_filename

router = APIRouter(prefix="/api/documents", tags=["documents"])


@router.get("", response_model=list[DocumentOut])
def list_documents(
    folder_id: Optional[int] = Query(None),
    search: Optional[str] = Query(None),
    tags: Optional[str] = Query(None),
    status: Optional[str] = Query(None),
    skip: int = Query(0, ge=0),
    limit: int = Query(100, le=500),
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    q = db.query(Document)
    if folder_id is not None:
        q = q.filter(Document.folder_id == folder_id)
    if search:
        like = f"%{search}%"
        full_text_ids = search_documents(search, limit=1000)
        text_conditions = [
            (Document.name.ilike(like))
            | (Document.title.ilike(like))
            | (Document.tags.ilike(like))
            | (cast(Document.metadata_json, String).ilike(like))
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
    q = q.order_by(Document.updated_at.desc()).offset(skip).limit(limit)
    return q.all()


@router.get("/{doc_id}", response_model=DocumentOut)
def get_document(
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
    return d


def _upload_one(
    db: Session,
    user: User,
    folder: Folder,
    file: UploadFile,
    title: Optional[str] = None,
    tags: str = "",
    metadata: Optional[dict] = None,
    template_id: Optional[int] = None,
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
    try:
        size = save_upload(file.file, tmp_path)
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
        )
        db.add(d)
        db.flush()
        dest_dir = doc_storage_dir(d.id)
        ext = Path(name).suffix
        dest = dest_dir / f"v1{ext}"
        shutil.move(str(tmp_path), str(dest))
        d.file_path = str(dest)
        d.size = dest.stat().st_size
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
    audit(db, user, "DOCUMENT_CREATE", "document", d.id, f"Uploaded {name} to folder {folder.id}")
    return d


@router.post("", response_model=DocumentOut)
def upload_document(
    folder_id: int = Form(...),
    title: Optional[str] = Form(None),
    tags: Optional[str] = Form(""),
    metadata: Optional[str] = Form("{}"),
    template_id: Optional[int] = Form(None),
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
        raise HTTPException(status_code=400, detail="Invalid metadata JSON")
    return _upload_one(db, user, f, file, title=title, tags=tags, metadata=meta, template_id=template_id)


@router.post("/bulk", response_model=list[DocumentOut])
def bulk_upload(
    folder_id: int = Form(...),
    tags: Optional[str] = Form(""),
    metadata: Optional[str] = Form("{}"),
    template_id: Optional[int] = Form(None),
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
        raise HTTPException(status_code=400, detail="Invalid metadata JSON")
    results = []
    for file in files:
        try:
            d = _upload_one(db, user, f, file, tags=tags, metadata=meta, template_id=template_id)
            results.append(d)
        except HTTPException:
            raise
        except Exception as exc:
            audit(db, user, "BULK_UPLOAD_ERROR", "document", None, f"{file.filename}: {exc}")
    return results


@router.get("/{doc_id}/download")
def download_document(
    doc_id: int,
    version: Optional[int] = Query(None, ge=1, alias="v"),
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
    comment: Optional[str] = Form(""),
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


@router.put("/{doc_id}", response_model=DocumentOut)
def update_document(
    doc_id: int,
    title: Optional[str] = Form(None),
    tags: Optional[str] = Form(None),
    metadata: Optional[str] = Form(None),
    status: Optional[str] = Form(None),
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    d = db.get(Document, doc_id)
    if not d:
        raise HTTPException(status_code=404, detail="Document not found")
    f = db.get(Folder, d.folder_id)
    if not has_permission(db, user, "write", f, d):
        raise HTTPException(status_code=403, detail="No permission")
    if title is not None:
        d.title = title
    if tags is not None:
        d.tags = tags
    if metadata is not None:
        try:
            d.metadata_json = json.loads(metadata)
        except Exception:
            raise HTTPException(status_code=400, detail="Invalid metadata JSON")
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
    d.updated_at = now()
    db.commit()
    db.refresh(d)
    index_document(d.id, d.title, d.tags, d.file_path, d.size)
    audit(db, user, "DOCUMENT_UPDATE", "document", d.id, "Updated metadata/status")
    return d


@router.delete("/{doc_id}")
def delete_document(
    doc_id: int,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    d = db.get(Document, doc_id)
    if not d:
        raise HTTPException(status_code=404, detail="Document not found")
    f = db.get(Folder, d.folder_id)
    if not has_permission(db, user, "delete", f, d):
        raise HTTPException(status_code=403, detail="No permission")
    ddir = doc_storage_dir(d.id)
    if ddir.exists():
        shutil.rmtree(ddir)
    remove_document(doc_id)
    # Purge rows that reference this document (FK enforcement is on, and
    # orphaned versions/comments/shares should not outlive the document).
    instance_ids = [
        row[0]
        for row in db.query(WorkflowInstance.id)
        .filter(WorkflowInstance.document_id == doc_id)
        .all()
    ]
    if instance_ids:
        db.query(Task).filter(Task.instance_id.in_(instance_ids)).delete(synchronize_session=False)
        db.query(WorkflowInstance).filter(WorkflowInstance.id.in_(instance_ids)).delete(
            synchronize_session=False
        )
    db.query(Comment).filter(Comment.document_id == doc_id).delete(synchronize_session=False)
    db.query(ShareLink).filter(ShareLink.document_id == doc_id).delete(synchronize_session=False)
    db.query(DocumentVersion).filter(DocumentVersion.document_id == doc_id).delete(
        synchronize_session=False
    )
    # Calendar events may outlive the document; just detach the reference.
    db.query(CalendarEvent).filter(CalendarEvent.document_id == doc_id).update(
        {"document_id": None}
    )
    db.delete(d)
    db.commit()
    audit(db, user, "DOCUMENT_DELETE", "document", doc_id, f"Deleted document {d.name}")
    return {"ok": True}
