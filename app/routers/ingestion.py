"""Ingestion routes: watched/import folders, email import."""
from __future__ import annotations

import email
import imaplib
import json
import mimetypes
import os
import secrets
import shutil
import ssl
import tempfile
from datetime import datetime, timedelta
from pathlib import Path
from typing import Optional

from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile, status
from sqlalchemy.orm import Session

from app import database
from app.audit import audit
from app.database import get_db, now
from app.indexing import index_document
from app.models import Document, DocumentVersion, Folder, ImportFolder, User
from app.permissions import has_permission
from app.schemas import EmailImportRequest, ImportFolderCreate, ImportFolderOut
from app.security import get_current_user, require_role
from app.storage import (
    doc_storage_dir,
    safe_filename,
    save_upload,
    validate_upload_filename,
)

router = APIRouter(prefix="/api/import", tags=["ingestion"])


def _create_document_from_file(
    db: Session,
    user: User,
    folder: Folder,
    file_path: Path,
    original_name: str,
    title: Optional[str] = None,
    tags: str = "",
    metadata: Optional[dict] = None,
    delete_source: bool = False,
):
    """Create a Document and version from a filesystem path (used by importers)."""
    name = safe_filename(original_name)
    validate_upload_filename(name)
    size = file_path.stat().st_size
    mime = mimetypes.guess_type(name)[0] or "application/octet-stream"
    d = Document(
        name=name,
        title=title or name,
        folder_id=folder.id,
        tags=tags,
        metadata_json=metadata or {},
        created_by=user.id,
        size=size,
        mime=mime,
        file_path=str(file_path),
    )
    db.add(d)
    db.flush()
    dest_dir = doc_storage_dir(d.id)
    ext = Path(name).suffix
    dest = dest_dir / f"v1{ext}"
    if delete_source:
        shutil.move(str(file_path), str(dest))
    else:
        shutil.copy2(str(file_path), str(dest))
    d.file_path = str(dest)
    d.size = dest.stat().st_size
    v = DocumentVersion(
        document_id=d.id,
        version_number=1,
        file_path=str(dest),
        size=d.size,
        created_by=user.id,
        comment="Imported",
    )
    db.add(v)
    db.commit()
    db.refresh(d)
    index_document(d.id, d.title, d.tags, d.file_path, d.size)
    audit(db, user, "DOCUMENT_IMPORT", "document", d.id, f"Imported {name} from {file_path}")
    return d


@router.get("/folders", response_model=list[ImportFolderOut])
def list_import_folders(
    db: Session = Depends(get_db),
    user: User = Depends(require_role("superadmin", "admin")),
):
    return db.query(ImportFolder).all()


@router.post("/folders", response_model=ImportFolderOut)
def create_import_folder(
    payload: ImportFolderCreate,
    db: Session = Depends(get_db),
    user: User = Depends(require_role("superadmin", "admin")),
):
    target = db.get(Folder, payload.target_folder_id)
    if not target:
        raise HTTPException(status_code=404, detail="Target folder not found")
    imp = ImportFolder(
        name=payload.name,
        local_path=payload.local_path,
        target_folder_id=payload.target_folder_id,
        recursive=payload.recursive,
        delete_after_import=payload.delete_after_import,
        created_by=user.id,
    )
    db.add(imp)
    db.commit()
    db.refresh(imp)
    audit(db, user, "IMPORT_FOLDER_CREATE", "import_folder", imp.id, imp.name)
    return imp


@router.post("/folders/{import_id}/scan")
def scan_import_folder(
    import_id: int,
    db: Session = Depends(get_db),
    user: User = Depends(require_role("superadmin", "admin", "manager")),
):
    imp = db.get(ImportFolder, import_id)
    if not imp:
        raise HTTPException(status_code=404, detail="Import folder not found")
    target = db.get(Folder, imp.target_folder_id)
    if not target:
        raise HTTPException(status_code=404, detail="Target folder not found")
    path = Path(imp.local_path)
    if not path.is_dir():
        raise HTTPException(status_code=400, detail=f"Path does not exist: {imp.local_path}")

    pattern = "**/*" if imp.recursive else "*"
    files = [p for p in path.glob(pattern) if p.is_file() and not p.name.startswith(".")]
    imported = 0
    for src in files:
        try:
            _create_document_from_file(
                db,
                user,
                target,
                src,
                src.name,
                title=src.stem,
                delete_source=imp.delete_after_import,
            )
            imported += 1
        except Exception as exc:
            audit(db, user, "IMPORT_FOLDER_ERROR", "import_folder", imp.id, f"{src.name}: {exc}")
    imp.last_scan = now()
    db.commit()
    audit(db, user, "IMPORT_FOLDER_SCAN", "import_folder", imp.id, f"Imported {imported} files")
    return {"scanned": len(files), "imported": imported}


@router.delete("/folders/{import_id}")
def delete_import_folder(
    import_id: int,
    db: Session = Depends(get_db),
    user: User = Depends(require_role("superadmin", "admin")),
):
    imp = db.get(ImportFolder, import_id)
    if not imp:
        raise HTTPException(status_code=404, detail="Import folder not found")
    db.delete(imp)
    db.commit()
    audit(db, user, "IMPORT_FOLDER_DELETE", "import_folder", import_id, imp.name)
    return {"ok": True}


@router.post("/email")
def import_email(
    payload: EmailImportRequest,
    db: Session = Depends(get_db),
    user: User = Depends(require_role("superadmin", "admin", "manager")),
):
    target = db.get(Folder, payload.target_folder_id)
    if not target:
        raise HTTPException(status_code=404, detail="Target folder not found")

    try:
        ctx = ssl.create_default_context()
        mail = imaplib.IMAP4_SSL(payload.host, payload.port, ssl_context=ctx)
        mail.login(payload.username, payload.password)
        mail.select(payload.mailbox)
        since = (datetime.utcnow() - timedelta(days=payload.since_days)).strftime("%d-%b-%Y")
        _, data = mail.search(None, f'(SINCE "{since}")')
        msg_ids = data[0].split()
        imported = 0
        for msg_id in msg_ids:
            _, msg_data = mail.fetch(msg_id, "(RFC822)")
            raw = msg_data[0][1]
            msg = email.message_from_bytes(raw)
            subject = msg.get("Subject", "email")
            for part in msg.walk():
                if part.get_content_maintype() == "multipart":
                    continue
                filename = part.get_filename()
                if not filename:
                    continue
                with tempfile.NamedTemporaryFile(delete=False) as tmp:
                    tmp.write(part.get_payload(decode=True) or b"")
                    tmp_path = Path(tmp.name)
                try:
                    _create_document_from_file(
                        db,
                        user,
                        target,
                        tmp_path,
                        filename,
                        title=f"{subject} - {filename}",
                        tags="email-import",
                        metadata={"email_subject": subject},
                        delete_source=True,
                    )
                    imported += 1
                except Exception as exc:
                    tmp_path.unlink(missing_ok=True)
                    audit(db, user, "EMAIL_IMPORT_ERROR", "document", None, f"{filename}: {exc}")
            if payload.delete_after_import:
                mail.store(msg_id, "+FLAGS", "\\Deleted")
        if payload.delete_after_import:
            mail.expunge()
        mail.close()
        mail.logout()
    except Exception as exc:
        raise HTTPException(status_code=400, detail=f"IMAP error: {exc}") from exc

    audit(db, user, "EMAIL_IMPORT", "folder", target.id, f"Imported {imported} attachments from {payload.username}")
    return {"imported": imported}
