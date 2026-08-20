"""Extra features: faceted search, archive export, backup, shared calendar."""
from __future__ import annotations

import sqlite3
import zipfile
from datetime import datetime
from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import FileResponse
from sqlalchemy.orm import Session

from app import database
from app.audit import audit
from app.database import DB_PATH, get_db
from app.models import CalendarEvent, Document, Folder, User
from app.permissions import has_permission, readable_folder_ids
from app.schemas import CalendarEventCreate, CalendarEventOut, FacetsOut
from app.security import get_current_user, require_role

router = APIRouter(prefix="/api", tags=["extras"])

MAX_EXPORT_DOCUMENTS = 2000
BACKUP_RETENTION = 5


# ---------------------------------------------------------------------------
# Faceted navigation
# ---------------------------------------------------------------------------
@router.get("/facets", response_model=FacetsOut)
def facets(
    folder_id: int | None = None,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    q = db.query(Document).filter(Document.deleted_at.is_(None))
    if folder_id is not None:
        q = q.filter(Document.folder_id == folder_id)
    if user.role not in ("superadmin", "admin"):
        folders = readable_folder_ids(db, user)
        cond = Document.created_by == user.id
        if folders:
            cond = cond | Document.folder_id.in_(folders)
        q = q.filter(cond)
    docs = q.all()

    by_status: dict[str, int] = {}
    by_mime: dict[str, int] = {}
    by_tag: dict[str, int] = {}
    by_extension: dict[str, int] = {}
    by_source: dict[str, int] = {}
    overdue = 0
    from app.database import now as utcnow

    stamp = utcnow()
    for d in docs:
        by_status[d.status] = by_status.get(d.status, 0) + 1
        mime = (d.mime or "unknown").split(";")[0]
        by_mime[mime] = by_mime.get(mime, 0) + 1
        ext = Path(d.name).suffix.lower() or "none"
        by_extension[ext] = by_extension.get(ext, 0) + 1
        src = d.source or "upload"
        by_source[src] = by_source.get(src, 0) + 1
        if d.due_date and d.due_date < stamp:
            overdue += 1
        for tag in (d.tags or "").split(","):
            tag = tag.strip()
            if tag:
                by_tag[tag] = by_tag.get(tag, 0) + 1

    return {
        "total": len(docs),
        "by_status": by_status,
        "by_mime": by_mime,
        "by_tag": by_tag,
        "by_extension": by_extension,
        "by_source": by_source,
        "overdue": overdue,
    }


# ---------------------------------------------------------------------------
# Archive export (zip of a folder subtree)
# ---------------------------------------------------------------------------
def _collect_subtree(db: Session, folder: Folder) -> list[Folder]:
    result = [folder]
    children = db.query(Folder).filter(Folder.parent_id == folder.id).all()
    for c in children:
        result.extend(_collect_subtree(db, c))
    return result


@router.get("/folders/{folder_id}/export")
def export_folder(
    folder_id: int,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    f = db.get(Folder, folder_id)
    if not f:
        raise HTTPException(status_code=404, detail="Folder not found")
    if not has_permission(db, user, "read", f):
        raise HTTPException(status_code=403, detail="No permission")

    folders = _collect_subtree(db, f)
    if user.role not in ("superadmin", "admin"):
        # A read grant on the root must not expose documents in child folders
        # whose ACLs exclude the caller — keep only readable folders.
        allowed = readable_folder_ids(db, user)
        folders = [fo for fo in folders if fo.id in allowed]
    if not folders:
        raise HTTPException(status_code=403, detail="No permission")
    paths = {fo.id: fo.name for fo in folders}
    # Build relative paths for nested folders
    rel: dict[int, str] = {}

    def rel_path(fo: Folder) -> str:
        if fo.id in rel:
            return rel[fo.id]
        if fo.id == f.id or fo.parent_id not in paths:
            rel[fo.id] = fo.name
        else:
            parent = next(x for x in folders if x.id == fo.parent_id)
            rel[fo.id] = rel_path(parent) + "/" + fo.name
        return rel[fo.id]

    def safe_arcname(segment: str) -> str:
        # Defensive: never let a folder/document name escape the archive root.
        return segment.replace("/", "_").replace("\\", "_").replace("..", "_")

    export_dir = database.STORAGE_DIR / "exports"
    export_dir.mkdir(parents=True, exist_ok=True)
    zip_path = export_dir / f"folder_{folder_id}_{datetime.utcnow().strftime('%Y%m%d%H%M%S')}.zip"

    count = 0
    with zipfile.ZipFile(zip_path, "w", zipfile.ZIP_DEFLATED) as zf:
        for fo in folders:
            docs = db.query(Document).filter(Document.folder_id == fo.id).all()
            for d in docs:
                if count >= MAX_EXPORT_DOCUMENTS:
                    break
                p = Path(d.file_path)
                if p.exists():
                    zf.write(p, arcname=f"{safe_arcname(rel_path(fo))}/{safe_arcname(d.name)}")
                    count += 1

    # Keep the exports directory from growing without bound.
    for old in sorted(export_dir.glob("*.zip"), key=lambda p: p.stat().st_mtime, reverse=True)[10:]:
        old.unlink(missing_ok=True)

    audit(db, user, "FOLDER_EXPORT", "folder", folder_id, f"Exported {count} documents")
    return FileResponse(zip_path, filename=zip_path.name, media_type="application/zip")


# ---------------------------------------------------------------------------
# Backup (database + storage manifest)
# ---------------------------------------------------------------------------
@router.post("/backup")
def create_backup(
    db: Session = Depends(get_db),
    user: User = Depends(require_role("superadmin", "admin")),
):
    backup_dir = database.STORAGE_DIR / "backups"
    backup_dir.mkdir(parents=True, exist_ok=True)
    stamp = datetime.utcnow().strftime("%Y%m%d%H%M%S")
    zip_path = backup_dir / f"backup_{stamp}.zip"

    files = 0
    with zipfile.ZipFile(zip_path, "w", zipfile.ZIP_DEFLATED) as zf:
        if DB_PATH.exists():
            # Byte-copying a live SQLite file can capture a torn snapshot; use
            # SQLite's online backup API to obtain a consistent copy instead.
            tmp_db = backup_dir / f".db_{stamp}"
            try:
                src = sqlite3.connect(str(DB_PATH))
                dst = sqlite3.connect(str(tmp_db))
                src.backup(dst)
                dst.close()
                src.close()
                zf.write(tmp_db, arcname="edms.db")
                files += 1
            finally:
                tmp_db.unlink(missing_ok=True)
        docs_root = database.STORAGE_DIR / "documents"
        if docs_root.exists():
            for p in docs_root.rglob("*"):
                if p.is_file():
                    zf.write(p, arcname=str(p.relative_to(database.STORAGE_DIR)))
                    files += 1

    # Retention: keep only the most recent backups.
    for old in sorted(
        backup_dir.glob("backup_*.zip"), key=lambda p: p.stat().st_mtime, reverse=True
    )[BACKUP_RETENTION:]:
        old.unlink(missing_ok=True)

    audit(db, user, "BACKUP_CREATE", None, None, f"Backup {zip_path.name} with {files} files")
    return {"ok": True, "file": zip_path.name, "files": files, "size": zip_path.stat().st_size}


@router.get("/backup")
def list_backups(
    db: Session = Depends(get_db),
    user: User = Depends(require_role("superadmin", "admin")),
):
    backup_dir = database.STORAGE_DIR / "backups"
    if not backup_dir.exists():
        return []
    return [
        {"file": p.name, "size": p.stat().st_size, "created": p.stat().st_mtime}
        for p in sorted(backup_dir.glob("backup_*.zip"), reverse=True)
    ]


@router.post("/backup/restore")
def restore_backup(
    file: str,
    db: Session = Depends(get_db),
    user: User = Depends(require_role("superadmin", "admin")),
):
    backup_dir = database.STORAGE_DIR / "backups"
    zip_path = backup_dir / Path(file).name
    if not zip_path.exists() or zip_path.suffix.lower() != ".zip":
        raise HTTPException(404, "Backup not found")
    dest = database.STORAGE_DIR / "restores" / zip_path.stem
    dest.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(zip_path) as zf:
        zf.extractall(dest)
    restored = 0
    docs_src = dest / "documents"
    docs_dst = database.STORAGE_DIR / "documents"
    if docs_src.exists():
        docs_dst.mkdir(parents=True, exist_ok=True)
        for p in docs_src.rglob("*"):
            if not p.is_file():
                continue
            rel = p.relative_to(docs_src)
            target = docs_dst / rel
            target.parent.mkdir(parents=True, exist_ok=True)
            if not target.exists():
                target.write_bytes(p.read_bytes())
                restored += 1
    audit(db, user, "BACKUP_RESTORE", None, None, zip_path.name)
    return {"ok": True, "extracted": str(dest), "files": restored, "db_copy": str(dest / "edms.db")}


# ---------------------------------------------------------------------------
# Shared calendar
# ---------------------------------------------------------------------------
@router.get("/calendar", response_model=list[CalendarEventOut])
def list_events(
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    if user.role in ("superadmin", "admin"):
        return db.query(CalendarEvent).order_by(CalendarEvent.start_at).all()
    # Regular users see only their own events (an event's title/description and
    # document reference are private to its creator).
    return (
        db.query(CalendarEvent)
        .filter(CalendarEvent.created_by == user.id)
        .order_by(CalendarEvent.start_at)
        .all()
    )


@router.post("/calendar", response_model=CalendarEventOut)
def create_event(
    payload: CalendarEventCreate,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    if payload.document_id is not None:
        d = db.get(Document, payload.document_id)
        if not d:
            raise HTTPException(status_code=404, detail="Document not found")
        f = db.get(Folder, d.folder_id)
        if not has_permission(db, user, "read", f, d):
            raise HTTPException(status_code=403, detail="No permission")
    e = CalendarEvent(
        title=payload.title,
        description=payload.description,
        start_at=payload.start_at,
        end_at=payload.end_at,
        document_id=payload.document_id,
        created_by=user.id,
    )
    db.add(e)
    db.commit()
    db.refresh(e)
    audit(db, user, "CALENDAR_CREATE", "calendar_event", e.id, e.title)
    return e


@router.delete("/calendar/{event_id}")
def delete_event(
    event_id: int,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    e = db.get(CalendarEvent, event_id)
    if not e:
        raise HTTPException(status_code=404, detail="Event not found")
    if e.created_by != user.id and user.role not in ("superadmin", "admin"):
        raise HTTPException(status_code=403, detail="Not your event")
    db.delete(e)
    db.commit()
    audit(db, user, "CALENDAR_DELETE", "calendar_event", event_id, e.title)
    return {"ok": True}
