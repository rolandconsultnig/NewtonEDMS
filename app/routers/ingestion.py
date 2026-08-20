"""Ingestion routes: watched/import folders, email import."""
from __future__ import annotations

import email
import imaplib
import mimetypes
import shutil
import ssl
import tempfile
from datetime import datetime, timedelta
from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from app import database
from app.audit import audit
from app.config import BASE_DIR, settings
from app.database import get_db, now
from app.indexing import index_document
from app.joex import schedule_document
from app.models import Document, DocumentVersion, Folder, ImportFolder, User
from app.crypto import encrypt_secret
from app.permissions import has_permission
from app.schemas import EmailImportRequest, ImportFolderCreate, ImportFolderOut
from app.security import require_role
from app.storage import (
    doc_storage_dir,
    safe_filename,
    validate_upload_filename,
)

router = APIRouter(prefix="/api/import", tags=["ingestion"])

# Guards for watched-folder paths: never allow importing the app's own files,
# its database, or its storage tree (recursive self-import).
_FORBIDDEN_ROOTS = (BASE_DIR,)


def _validate_import_path(local_path: str) -> Path:
    """Resolve and validate a watched-folder path against the configured root.

    ``EDMS_IMPORT_ROOT`` is the only subtree import folders may watch; when it
    is unset the feature is disabled. This prevents an admin-only misconfig or
    a compromised admin account from turning the DMS into an arbitrary
    filesystem exfiltration/deletion tool.
    """
    if not (settings.import_root or "").strip():
        raise HTTPException(
            status_code=400,
            detail="Import folders are disabled: set EDMS_IMPORT_ROOT to enable them",
        )
    allowed_root = Path(settings.import_root).resolve()
    allowed_root.mkdir(parents=True, exist_ok=True)
    try:
        resolved = Path(local_path).resolve()
        resolved.relative_to(allowed_root)
    except ValueError:
        raise HTTPException(
            status_code=400,
            detail=f"Import path must live under the configured import root ({allowed_root})",
        ) from None
    for forbidden in _FORBIDDEN_ROOTS:
        if resolved == forbidden or allowed_root == forbidden:
            raise HTTPException(status_code=400, detail="Import path is not allowed")
    if database.STORAGE_DIR.resolve() in resolved.parents or resolved == database.STORAGE_DIR.resolve():
        raise HTTPException(status_code=400, detail="Import path may not include application storage")
    return resolved


def _create_document_from_file(
    db: Session,
    user: User,
    folder: Folder,
    file_path: Path,
    original_name: str,
    title: str | None = None,
    tags: str = "",
    metadata: dict | None = None,
    delete_source: bool = False,
):
    """Create a Document and version from a filesystem path (used by importers)."""
    name = safe_filename(original_name)
    validate_upload_filename(name)
    size = file_path.stat().st_size
    if size > settings.max_upload_bytes:
        raise HTTPException(
            status_code=413,
            detail=f"{name} exceeds the {settings.max_upload_bytes} byte import limit",
        )
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
        source="import",
        processing_status="pending",
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
    schedule_document(db, d.id, created_by=user.id)
    try:
        from app.hooks import after_document_create

        after_document_create(db, d)
    except Exception:
        pass
    audit(db, user, "DOCUMENT_IMPORT", "document", d.id, f"Imported {name}")
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
    protocol = (payload.protocol or "local").lower()
    if protocol == "local":
        resolved = _validate_import_path(payload.local_path)
        if not resolved.is_dir():
            raise HTTPException(status_code=400, detail="Import path is not a directory")
        stored_path = str(resolved)
    else:
        stored_path = payload.local_path or f"{protocol}://{payload.host or ''}{payload.remote_path or '/'}"
    imp = ImportFolder(
        name=payload.name,
        local_path=stored_path,
        target_folder_id=payload.target_folder_id,
        recursive=payload.recursive,
        delete_after_import=payload.delete_after_import,
        created_by=user.id,
        protocol=protocol,
        host=payload.host,
        port=payload.port,
        username=payload.username,
        password_enc=encrypt_secret(payload.password or ""),
        remote_path=payload.remote_path,
    )
    db.add(imp)
    db.commit()
    db.refresh(imp)
    audit(db, user, "IMPORT_FOLDER_CREATE", "import_folder", imp.id, imp.name)
    return imp


def execute_import_scan(db: Session, user: User, imp: ImportFolder) -> dict:
    """Run a watched-folder or remote import. Callable from the scheduler."""
    target = db.get(Folder, imp.target_folder_id)
    if not target:
        raise HTTPException(status_code=404, detail="Target folder not found")
    if not has_permission(db, user, "write", target):
        raise HTTPException(status_code=403, detail="No permission to import into this folder")
    protocol = (imp.protocol or "local").lower()
    if protocol == "ftp":
        scanned, imported = _scan_ftp(db, user, imp, target)
    elif protocol == "smb":
        scanned, imported = _scan_smb(db, user, imp, target)
    else:
        path = _validate_import_path(imp.local_path)
        if not path.is_dir():
            raise HTTPException(status_code=400, detail="Import path no longer exists")
        scanned, imported = _scan_local(db, user, imp, target, path)
    imp.last_scan = now()
    db.commit()
    audit(db, user, "IMPORT_FOLDER_SCAN", "import_folder", imp.id, f"Imported {imported} files")
    return {"scanned": scanned, "imported": imported}


def _scan_local(db, user, imp, target, path: Path) -> tuple[int, int]:
    pattern = "**/*" if imp.recursive else "*"
    scanned = 0
    imported = 0
    for src in path.glob(pattern):
        if scanned >= settings.max_import_files_per_scan:
            break
        if not src.is_file() or src.name.startswith("."):
            continue
        scanned += 1
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
            audit(
                db, user, "IMPORT_FOLDER_ERROR", "import_folder", imp.id,
                f"{src.name}: {type(exc).__name__}",
            )
    return scanned, imported


def _scan_ftp(db, user, imp, target) -> tuple[int, int]:
    import ftplib

    from app.crypto import decrypt_secret

    password = decrypt_secret(imp.password_enc or "")
    ftp = ftplib.FTP()
    ftp.connect(imp.host or "localhost", imp.port or 21, timeout=20)
    ftp.login(imp.username or "anonymous", password or "")
    if imp.remote_path:
        ftp.cwd(imp.remote_path)
    names = ftp.nlst()
    scanned = 0
    imported = 0
    for name in names:
        if name in (".", "..") or name.startswith("."):
            continue
        scanned += 1
        if scanned > settings.max_import_files_per_scan:
            break
        tmp = tempfile.NamedTemporaryFile(delete=False)
        tmp_path = Path(tmp.name)
        try:
            ftp.retrbinary(f"RETR {name}", tmp.write)
            tmp.close()
            _create_document_from_file(db, user, target, tmp_path, name, title=Path(name).stem)
            imported += 1
        except Exception as exc:
            audit(db, user, "IMPORT_FOLDER_ERROR", "import_folder", imp.id, f"{name}: {type(exc).__name__}")
        finally:
            try:
                tmp.close()
            except Exception:
                pass
            tmp_path.unlink(missing_ok=True)
    try:
        ftp.quit()
    except Exception:
        ftp.close()
    return scanned, imported


def _scan_smb(db, user, imp, target) -> tuple[int, int]:
    import tempfile

    from app.connectors import smb_fetch, smb_list
    from app.crypto import decrypt_secret

    share = (imp.remote_path or "documents").replace("\\", "/").split("/")[0]
    rest = "/".join((imp.remote_path or "").replace("\\", "/").split("/")[1:])
    cfg = {
        "host": imp.host,
        "share": share or "documents",
        "path": rest,
        "username": imp.username or "",
        "password": decrypt_secret(imp.password_enc or "") if imp.password_enc else "",
    }
    entries = smb_list(cfg)
    scanned = 0
    imported = 0
    for entry in entries:
        if entry.get("is_dir"):
            continue
        scanned += 1
        if scanned > settings.max_import_files_per_scan:
            break
        tmp = Path(tempfile.mkstemp(suffix=Path(entry["name"]).suffix)[1])
        try:
            smb_fetch(cfg, entry["path"], tmp)
            _create_document_from_file(db, user, target, tmp, entry["name"], title=Path(entry["name"]).stem)
            imported += 1
        except Exception as exc:
            audit(
                db, user, "IMPORT_FOLDER_ERROR", "import_folder", imp.id,
                f"{entry.get('name')}: {type(exc).__name__}",
            )
        finally:
            tmp.unlink(missing_ok=True)
    return scanned, imported


@router.post("/folders/{import_id}/scan")
def scan_import_folder(
    import_id: int,
    db: Session = Depends(get_db),
    user: User = Depends(require_role("superadmin", "admin")),
):
    imp = db.get(ImportFolder, import_id)
    if not imp:
        raise HTTPException(status_code=404, detail="Import folder not found")
    return execute_import_scan(db, user, imp)


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
    user: User = Depends(require_role("superadmin", "admin")),
):
    target = db.get(Folder, payload.target_folder_id)
    if not target:
        raise HTTPException(status_code=404, detail="Target folder not found")
    if not has_permission(db, user, "write", target):
        raise HTTPException(status_code=403, detail="No permission to import into this folder")
    # Clamp the fetch window; an unbounded value could pull an entire mailbox.
    since_days = max(1, min(payload.since_days, 90))
    # Mailbox names are passed verbatim to the IMAP server; keep them plain.
    if not payload.mailbox.replace("-", "").replace("_").isalnum():
        raise HTTPException(status_code=400, detail="Invalid mailbox name")

    imported = 0
    try:
        ctx = ssl.create_default_context()
        mail = imaplib.IMAP4_SSL(payload.host, payload.port, ssl_context=ctx)
        mail.login(payload.username, payload.password)
        mail.select(payload.mailbox)
        since = (datetime.utcnow() - timedelta(days=since_days)).strftime("%d-%b-%Y")
        _, data = mail.search(None, f'(SINCE "{since}")')
        msg_ids = data[0].split()[: settings.max_import_files_per_scan]
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
                    audit(
                        db, user, "EMAIL_IMPORT_ERROR", "document", None,
                        f"{safe_filename(filename)}: {type(exc).__name__}",
                    )
            if payload.delete_after_import:
                mail.store(msg_id, "+FLAGS", "\\Deleted")
        if payload.delete_after_import:
            mail.expunge()
        mail.close()
        mail.logout()
    except HTTPException:
        raise
    except Exception:
        # Never echo raw IMAP errors (hostnames, server responses) to clients.
        raise HTTPException(status_code=400, detail="Email import failed") from None

    audit(db, user, "EMAIL_IMPORT", "folder", target.id, f"Imported {imported} attachments")
    return {"imported": imported}
