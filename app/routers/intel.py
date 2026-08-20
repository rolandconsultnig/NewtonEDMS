"""Intelligence APIs: catalogs, curation, dashboards, shares, jobs, ingest, i18n."""
from __future__ import annotations

import io
import json
import secrets
import shutil
import zipfile
from datetime import timedelta
from html import escape
from pathlib import Path

from fastapi import APIRouter, Depends, File, Form, HTTPException, Query, Request, UploadFile
from fastapi.responses import FileResponse, HTMLResponse, JSONResponse, StreamingResponse
from sqlalchemy.orm import Session

from app import database
from app.audit import audit
from app.branding import PRODUCT_NAME
from app.database import get_db, now
from app.fts import highlight as fts_highlight
from app.fts import search as fts_search
from app.i18n import load_catalog
from app.indexing import search_documents
from app.joex import enqueue, schedule_document
from app.miniquery import match as mini_match
from app.models import (
    Addon,
    AnonymousUpload,
    Collective,
    CollectiveMember,
    Contact,
    CustomField,
    Dashboard,
    Document,
    DocumentAttachment,
    Equipment,
    EventHook,
    Folder,
    JobLog,
    MailboxTask,
    MailSettings,
    MailTemplate,
    NotifyChannel,
    Organization,
    ProcessingJob,
    QueryShare,
    StorageStore,
    Tag,
    User,
)
from app.permissions import has_permission, readable_document_ids, readable_folder_ids
from app.querylang import apply_filters, parse_query
from app.security import get_current_user, get_password_hash, require_role, verify_password
from app.storage import doc_storage_dir, safe_filename, save_upload, validate_upload_filename

router = APIRouter(prefix="/api", tags=["intel"])
open_intel = APIRouter(tags=["open-intel"])


def _visible_docs(db: Session, user: User, q):
    if user.role not in ("superadmin", "admin"):
        from sqlalchemy import or_

        conditions = [Document.created_by == user.id]
        folders = readable_folder_ids(db, user)
        if folders:
            conditions.append(Document.folder_id.in_(folders))
        docs = readable_document_ids(db, user)
        if docs:
            conditions.append(Document.id.in_(docs))
        q = q.filter(or_(*conditions))
    from app.tenancy import filter_documents

    return filter_documents(q, user)


def _cid(user: User) -> int | None:
    return user.collective_id


# ---------------------------------------------------------------------------
# Organizations / equipment / persons extras
# ---------------------------------------------------------------------------
@router.get("/organizations")
def list_orgs(db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    q = db.query(Organization)
    if user.collective_id:
        q = q.filter((Organization.collective_id == user.collective_id) | Organization.collective_id.is_(None))
    return [
        {"id": o.id, "name": o.name, "websites": o.websites or [], "emails": o.emails or [], "notes": o.notes}
        for o in q.order_by(Organization.name).all()
    ]


@router.post("/organizations")
def create_org(
    name: str = Form(...),
    websites: str = Form(""),
    emails: str = Form(""),
    notes: str = Form(""),
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    o = Organization(
        name=name,
        websites=[w.strip() for w in websites.split(",") if w.strip()],
        emails=[e.strip() for e in emails.split(",") if e.strip()],
        notes=notes,
        collective_id=user.collective_id,
        created_by=user.id,
    )
    db.add(o)
    db.commit()
    db.refresh(o)
    return {"id": o.id, "name": o.name}


@router.delete("/organizations/{org_id}")
def delete_org(org_id: int, db: Session = Depends(get_db), user: User = Depends(require_role("superadmin", "admin", "manager"))):
    o = db.get(Organization, org_id)
    if not o:
        raise HTTPException(status_code=404, detail="Organization not found")
    db.query(Document).filter(Document.organization_id == org_id).update({"organization_id": None})
    db.delete(o)
    db.commit()
    return {"ok": True}


@router.get("/equipment")
def list_equipment(db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    q = db.query(Equipment)
    if user.collective_id:
        q = q.filter((Equipment.collective_id == user.collective_id) | Equipment.collective_id.is_(None))
    return [{"id": e.id, "name": e.name, "notes": e.notes} for e in q.order_by(Equipment.name).all()]


@router.post("/equipment")
def create_equipment(
    name: str = Form(...),
    notes: str = Form(""),
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    e = Equipment(name=name, notes=notes, collective_id=user.collective_id, created_by=user.id)
    db.add(e)
    db.commit()
    db.refresh(e)
    return {"id": e.id, "name": e.name}


@router.delete("/equipment/{eq_id}")
def delete_equipment(eq_id: int, db: Session = Depends(get_db), user: User = Depends(require_role("superadmin", "admin", "manager"))):
    e = db.get(Equipment, eq_id)
    if not e:
        raise HTTPException(status_code=404, detail="Equipment not found")
    db.query(Document).filter(Document.equipment_id == eq_id).update({"equipment_id": None})
    db.delete(e)
    db.commit()
    return {"ok": True}


# ---------------------------------------------------------------------------
# Collectives
# ---------------------------------------------------------------------------
@router.get("/collectives/current")
def current_collective(db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    c = db.get(Collective, user.collective_id) if user.collective_id else db.query(Collective).first()
    if not c:
        raise HTTPException(status_code=404, detail="No collective")
    return {
        "id": c.id,
        "name": c.name,
        "description": c.description,
        "language": c.language,
        "classifier_config": c.classifier_config or {},
        "invite_code": c.invite_code,
        "settings": c.settings or {},
    }


@router.put("/collectives/current")
def update_collective(
    payload: dict,
    db: Session = Depends(get_db),
    user: User = Depends(require_role("superadmin", "admin", "manager")),
):
    c = db.get(Collective, user.collective_id) if user.collective_id else db.query(Collective).first()
    if not c:
        raise HTTPException(status_code=404, detail="No collective")
    if "name" in payload:
        c.name = payload["name"]
    if "language" in payload:
        c.language = payload["language"]
    if "classifier_config" in payload:
        c.classifier_config = payload["classifier_config"]
    if "settings" in payload:
        c.settings = payload["settings"]
    if payload.get("rotate_invite"):
        c.invite_code = secrets.token_urlsafe(12)
    elif not c.invite_code:
        c.invite_code = secrets.token_urlsafe(12)
    db.commit()
    return {"ok": True, "invite_code": c.invite_code}


@router.post("/collectives/invite")
def join_collective(
    code: str = Form(...),
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    c = db.query(Collective).filter(Collective.invite_code == code).first()
    if not c:
        raise HTTPException(status_code=404, detail="Invite code not found")
    user.collective_id = c.id
    existing = (
        db.query(CollectiveMember)
        .filter(CollectiveMember.collective_id == c.id, CollectiveMember.user_id == user.id)
        .first()
    )
    if not existing:
        db.add(CollectiveMember(collective_id=c.id, user_id=user.id, role="member"))
    db.commit()
    return {"ok": True, "collective_id": c.id, "name": c.name}


@router.post("/collectives/switch")
def switch_collective(
    collective_id: int,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    m = (
        db.query(CollectiveMember)
        .filter(CollectiveMember.collective_id == collective_id, CollectiveMember.user_id == user.id)
        .first()
    )
    c = db.get(Collective, collective_id)
    if not c or (not m and user.role not in ("superadmin", "admin")):
        raise HTTPException(status_code=403, detail="Not a member of that collective")
    user.collective_id = c.id
    db.commit()
    return {"ok": True, "collective_id": c.id}


# ---------------------------------------------------------------------------
# Confirm / unconfirm / next
# ---------------------------------------------------------------------------
@router.post("/documents/{doc_id}/confirm")
def confirm_doc(doc_id: int, db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    d = db.get(Document, doc_id)
    if not d:
        raise HTTPException(status_code=404, detail="Document not found")
    d.confirmed = True
    d.confirmed_at = now()
    meta = dict(d.metadata_json or {})
    meta.pop("suggestions", None)
    d.metadata_json = meta
    db.commit()
    from app.events import emit

    emit(db, "item_confirmed", d)
    return {"ok": True, "confirmed": True}


@router.post("/documents/{doc_id}/unconfirm")
def unconfirm_doc(doc_id: int, db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    d = db.get(Document, doc_id)
    if not d:
        raise HTTPException(status_code=404, detail="Document not found")
    d.confirmed = False
    d.confirmed_at = None
    db.commit()
    return {"ok": True, "confirmed": False}


@router.get("/documents/next")
def next_item(
    q: str = "",
    after: int = 0,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    parsed = parse_query(q or "confirmed:new")
    qry = _visible_docs(db, user, db.query(Document).filter(Document.deleted_at.is_(None)))
    qry = apply_filters(qry, parsed, db)
    if after:
        qry = qry.filter(Document.id > after)
    d = qry.order_by(Document.id.asc()).first()
    if not d:
        return {"id": None}
    return {"id": d.id, "title": d.title}


# ---------------------------------------------------------------------------
# Thumbnails, highlight, download-all, group upload
# ---------------------------------------------------------------------------
@router.get("/documents/{doc_id}/thumbnail")
def thumbnail(doc_id: int, db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    d = db.get(Document, doc_id)
    if not d:
        raise HTTPException(status_code=404, detail="Document not found")
    f = db.get(Folder, d.folder_id)
    if not has_permission(db, user, "read", f, d):
        raise HTTPException(status_code=403, detail="No permission")
    path = Path(d.thumbnail_path) if d.thumbnail_path else None
    if not path or not path.exists():
        raise HTTPException(status_code=404, detail="No thumbnail")
    return FileResponse(path, media_type="image/jpeg")


@router.get("/documents/{doc_id}/highlight")
def highlight_text(
    doc_id: int,
    q: str = "",
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    d = db.get(Document, doc_id)
    if not d:
        raise HTTPException(status_code=404, detail="Document not found")
    return {"snippets": fts_highlight(d.extracted_text or "", q)}


@router.get("/documents/download-all")
def download_all(
    q: str = "",
    fmt: str = "original",
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    parsed = parse_query(q)
    qry = apply_filters(_visible_docs(db, user, db.query(Document).filter(Document.deleted_at.is_(None))), parsed, db)
    docs = qry.limit(500).all()
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf:
        for d in docs:
            dt = d.item_date or d.created_at or now()
            corr = ""
            if d.correspondent_id:
                c = db.get(Contact, d.correspondent_id)
                corr = safe_filename((c.name if c else "") or "unknown")
            else:
                corr = "unknown"
            folder = f"{dt.strftime('%Y-%m')}/{corr}"
            if fmt == "pdf" and d.pdf_file_path and Path(d.pdf_file_path).exists():
                zf.write(d.pdf_file_path, f"{folder}/{safe_filename(Path(d.pdf_file_path).name)}")
            elif d.file_path and Path(d.file_path).exists():
                zf.write(d.file_path, f"{folder}/{safe_filename(d.name)}")
    buf.seek(0)
    return StreamingResponse(
        buf,
        media_type="application/zip",
        headers={"Content-Disposition": 'attachment; filename="export.zip"'},
    )


@router.post("/documents/group")
def group_upload(
    folder_id: int = Form(...),
    title: str | None = Form(None),
    tags: str = Form(""),
    skip_duplicates: bool = Form(False),
    source_id: int | None = Form(None),
    files: list[UploadFile] = File(...),
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    folder = db.get(Folder, folder_id)
    if not folder or not has_permission(db, user, "write", folder):
        raise HTTPException(status_code=403, detail="No permission")
    first = files[0]
    name = safe_filename(first.filename)
    validate_upload_filename(name)
    tmp = database.STORAGE_DIR / f".group_{secrets.token_hex(8)}"
    size = save_upload(first.file, tmp)
    from app.hashing import file_sha256

    digest = file_sha256(tmp)
    if skip_duplicates and db.query(Document).filter(Document.content_hash == digest).first():
        tmp.unlink(missing_ok=True)
        raise HTTPException(status_code=409, detail="Duplicate file skipped")
    d = Document(
        name=name,
        title=title or name,
        folder_id=folder.id,
        tags=tags,
        created_by=user.id,
        size=size,
        mime=first.content_type,
        file_path=str(tmp),
        source="upload",
        source_id=source_id,
        processing_status="pending",
        content_hash=digest,
        confirmed=False,
    )
    db.add(d)
    db.flush()
    dest = doc_storage_dir(d.id) / f"v1{Path(name).suffix}"
    shutil.move(str(tmp), str(dest))
    d.file_path = str(dest)
    for extra in files[1:]:
        ename = safe_filename(extra.filename)
        validate_upload_filename(ename)
        att_path = doc_storage_dir(d.id) / "attachments" / ename
        att_path.parent.mkdir(parents=True, exist_ok=True)
        esize = save_upload(extra.file, att_path)
        db.add(
            DocumentAttachment(
                document_id=d.id,
                name=ename,
                file_path=str(att_path),
                size=esize,
                mime=extra.content_type,
                role="original",
            )
        )
    db.commit()
    db.refresh(d)
    schedule_document(db, d.id, created_by=user.id)
    return {"id": d.id, "title": d.title, "attachments": len(files)}


# ---------------------------------------------------------------------------
# Jobs: logs, retry, filters
# ---------------------------------------------------------------------------
@router.get("/jobs/{job_id}/logs")
def job_logs(job_id: int, db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    job = db.get(ProcessingJob, job_id)
    if not job:
        raise HTTPException(status_code=404, detail="Job not found")
    rows = db.query(JobLog).filter(JobLog.job_id == job_id).order_by(JobLog.id).all()
    return {
        "job_id": job_id,
        "status": job.status,
        "log_text": job.log_text or "",
        "entries": [{"id": r.id, "level": r.level, "message": r.message, "created_at": r.created_at} for r in rows],
    }


@router.post("/jobs/{job_id}/retry")
def retry_job(job_id: int, db: Session = Depends(get_db), user: User = Depends(require_role("superadmin", "admin"))):
    job = db.get(ProcessingJob, job_id)
    if not job:
        raise HTTPException(status_code=404, detail="Job not found")
    job.status = "queued"
    job.started_at = None
    job.finished_at = None
    job.message = "manually requeued"
    db.commit()
    return {"ok": True}


@router.get("/jobs/queue")
def job_queue(
    status: str | None = None,
    kind: str | None = None,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    q = db.query(ProcessingJob)
    if status:
        q = q.filter(ProcessingJob.status == status)
    if kind:
        q = q.filter(ProcessingJob.kind == kind)
    rows = q.order_by(ProcessingJob.id.desc()).limit(200).all()
    return [
        {
            "id": j.id,
            "kind": j.kind,
            "status": j.status,
            "document_id": j.document_id,
            "priority": j.priority,
            "attempts": j.attempts,
            "message": j.message,
            "created_at": j.created_at,
            "started_at": j.started_at,
            "finished_at": j.finished_at,
        }
        for j in rows
    ]


# ---------------------------------------------------------------------------
# Mailbox tasks, channels, event hooks, mail templates
# ---------------------------------------------------------------------------
@router.get("/mailbox-tasks")
def list_mailbox(db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    rows = db.query(MailboxTask).filter(MailboxTask.created_by == user.id).all()
    return [
        {
            "id": t.id,
            "name": t.name,
            "mail_settings_id": t.mail_settings_id,
            "folder_id": t.folder_id,
            "imap_folders": t.imap_folders,
            "received_since_hours": t.received_since_hours,
            "subject_glob": t.subject_glob,
            "file_glob": t.file_glob,
            "move_after_import": t.move_after_import,
            "schedule_minutes": t.schedule_minutes,
            "start_once": t.start_once,
            "enabled": t.enabled,
            "last_run": t.last_run,
        }
        for t in rows
    ]


@router.post("/mailbox-tasks")
def create_mailbox(payload: dict, db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    from app.models import MailSettings

    msid = payload.get("mail_settings_id")
    if not msid:
        first = db.query(MailSettings).first()
        if not first:
            raise HTTPException(status_code=400, detail="Save an IMAP/SMTP account first")
        msid = first.id
    t = MailboxTask(
        name=payload["name"],
        mail_settings_id=msid,
        folder_id=payload["folder_id"],
        imap_folders=payload.get("imap_folders") or "INBOX",
        received_since_hours=payload.get("received_since_hours") or 72,
        subject_glob=payload.get("subject_glob") or "*",
        file_glob=payload.get("file_glob") or "*",
        move_after_import=payload.get("move_after_import"),
        direction_from_from=payload.get("direction_from_from", True),
        schedule_minutes=payload.get("schedule_minutes") or 15,
        start_once=payload.get("start_once") or False,
        source_id=payload.get("source_id"),
        created_by=user.id,
    )
    db.add(t)
    db.commit()
    db.refresh(t)
    return {"id": t.id, "name": t.name}


@router.post("/mailbox-tasks/{task_id}/run")
def run_mailbox(task_id: int, db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    t = db.get(MailboxTask, task_id)
    if not t or t.created_by != user.id:
        raise HTTPException(status_code=404, detail="Task not found")
    from app.mailbox import run_task

    n = run_task(db, t)
    return {"imported": n}


@router.get("/notify-channels")
def list_channels(db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    return [
        {"id": c.id, "name": c.name, "kind": c.kind, "config": c.config or {}, "enabled": c.enabled}
        for c in db.query(NotifyChannel).filter(NotifyChannel.user_id == user.id).all()
    ]


@router.post("/notify-channels")
def create_channel(payload: dict, db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    ch = NotifyChannel(
        user_id=user.id,
        name=payload["name"],
        kind=payload["kind"],
        config=payload.get("config") or {},
    )
    db.add(ch)
    db.commit()
    db.refresh(ch)
    return {"id": ch.id, "name": ch.name, "kind": ch.kind}


@router.delete("/notify-channels/{channel_id}")
def delete_channel(channel_id: int, db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    ch = db.get(NotifyChannel, channel_id)
    if not ch or ch.user_id != user.id:
        raise HTTPException(status_code=404, detail="Channel not found")
    db.delete(ch)
    db.commit()
    return {"ok": True}


@router.get("/event-hooks")
def list_hooks(db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    return [
        {"id": h.id, "name": h.name, "event": h.event, "channel_id": h.channel_id, "mini_query": h.mini_query or {}, "enabled": h.enabled}
        for h in db.query(EventHook).filter(EventHook.user_id == user.id).all()
    ]


@router.post("/event-hooks")
def create_hook(payload: dict, db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    channel_id = payload.get("channel_id")
    if not channel_id and payload.get("url"):
        ch = NotifyChannel(user_id=user.id, name=payload.get("name") or payload.get("event") or "hook", kind="webhook", config={"url": payload["url"]})
        db.add(ch)
        db.flush()
        channel_id = ch.id
    if not channel_id:
        raise HTTPException(status_code=400, detail="channel_id or url required")
    h = EventHook(
        user_id=user.id,
        name=payload.get("name") or payload.get("event") or "hook",
        event=payload["event"],
        channel_id=channel_id,
        mini_query=payload.get("mini_query") or {},
    )
    db.add(h)
    db.commit()
    db.refresh(h)
    return {"id": h.id}


@router.get("/mail-templates")
def list_templates(db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    return [
        {"id": t.id, "name": t.name, "subject": t.subject, "body": t.body}
        for t in db.query(MailTemplate).filter(MailTemplate.user_id == user.id).all()
    ]


@router.post("/mail-templates")
def create_template(payload: dict, db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    t = MailTemplate(
        user_id=user.id,
        name=payload["name"],
        subject=payload.get("subject") or "",
        body=payload.get("body") or "",
    )
    db.add(t)
    db.commit()
    db.refresh(t)
    return {"id": t.id, "name": t.name}


# ---------------------------------------------------------------------------
# Query shares
# ---------------------------------------------------------------------------
@router.get("/query-shares")
def list_qshares(db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    rows = db.query(QueryShare).filter(QueryShare.created_by == user.id).all()
    return [
        {
            "id": r.id,
            "token": r.token,
            "name": r.name,
            "query": r.query,
            "enabled": r.enabled,
            "publish_until": r.publish_until,
            "url": f"/s/{r.token}",
            "password_protected": bool(r.password_hash),
        }
        for r in rows
    ]


@router.post("/query-shares")
def create_qshare(payload: dict, db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    pw = payload.get("password")
    row = QueryShare(
        token=secrets.token_urlsafe(18),
        name=payload["name"],
        query=payload.get("query") or "",
        static_ids=payload.get("static_ids") or [],
        publish_until=None,
        enabled=True,
        password_hash=get_password_hash(pw) if pw else None,
        created_by=user.id,
    )
    if payload.get("publish_days"):
        row.publish_until = now() + timedelta(days=int(payload["publish_days"]))
    db.add(row)
    db.commit()
    db.refresh(row)
    return {"id": row.id, "token": row.token, "url": f"/s/{row.token}"}


@router.post("/query-shares/{share_id}/toggle")
def toggle_qshare(share_id: int, db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    row = db.get(QueryShare, share_id)
    if not row or row.created_by != user.id:
        raise HTTPException(status_code=404, detail="Share not found")
    row.enabled = not row.enabled
    db.commit()
    return {"enabled": row.enabled}


# ---------------------------------------------------------------------------
# Dashboards: update layout + render widgets
# ---------------------------------------------------------------------------
@router.put("/dashboards/{dashboard_id}")
def update_dashboard(dashboard_id: int, payload: dict, db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    d = db.get(Dashboard, dashboard_id)
    if not d or (d.user_id != user.id and d.scope != "collective"):
        raise HTTPException(status_code=404, detail="Dashboard not found")
    if "name" in payload:
        d.name = payload["name"]
    if "layout" in payload:
        d.layout = payload["layout"]
    if "is_default" in payload:
        if payload["is_default"]:
            db.query(Dashboard).filter(Dashboard.user_id == user.id).update({"is_default": False})
        d.is_default = payload["is_default"]
    if "scope" in payload:
        d.scope = payload["scope"]
    db.commit()
    return {"ok": True, "id": d.id, "layout": d.layout}


@router.get("/dashboards/{dashboard_id}/render")
def render_dashboard(dashboard_id: int, db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    d = db.get(Dashboard, dashboard_id)
    if not d:
        raise HTTPException(status_code=404, detail="Dashboard not found")
    widgets = []
    for box in d.layout or []:
        kind = (box.get("kind") or box.get("type") or "markdown") if isinstance(box, dict) else "markdown"
        item = dict(box) if isinstance(box, dict) else {"kind": "markdown", "text": str(box)}
        if kind in ("stats", "query", "query-table", "table"):
            q = item.get("query") or ""
            parsed = parse_query(q)
            qry = apply_filters(_visible_docs(db, user, db.query(Document).filter(Document.deleted_at.is_(None))), parsed, db)
            rows = qry.order_by(Document.updated_at.desc()).limit(int(item.get("limit") or 10)).all()
            item["rows"] = [{"id": r.id, "title": r.title, "status": r.status, "tags": r.tags} for r in rows]
            item["count"] = qry.count()
        widgets.append(item)
    return {"id": d.id, "name": d.name, "layout": widgets, "scope": d.scope}


# ---------------------------------------------------------------------------
# Classifier, UI settings, i18n, addons zip
# ---------------------------------------------------------------------------
@router.post("/classifier/train")
def train_classifier(db: Session = Depends(get_db), user: User = Depends(require_role("superadmin", "admin", "manager"))):
    from app.classifier import train

    coll = db.get(Collective, user.collective_id) if user.collective_id else db.query(Collective).first()
    cfg = dict((coll.classifier_config if coll else None) or {})
    stats = train(db, whitelist=cfg.get("whitelist") or [], blacklist=cfg.get("blacklist") or [])
    return stats


@router.get("/classifier/status")
def classifier_status():
    from app.classifier import load_model

    m = load_model()
    if not m:
        return {"trained": False}
    return {"trained": True, "docs": m.get("n_docs"), "classes": len(m.get("class_docs") or {})}


@router.get("/ui-settings")
def get_ui(db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    return user.ui_settings or {}


@router.put("/ui-settings")
def put_ui(payload: dict, db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    cur = dict(user.ui_settings or {})
    cur.update(payload)
    user.ui_settings = cur
    if payload.get("locale"):
        user.locale = payload["locale"]
    db.commit()
    return cur


@router.get("/i18n/{locale}")
def i18n_catalog(locale: str):
    return load_catalog(locale)


@router.post("/addons/package")
def upload_addon_zip(
    file: UploadFile = File(...),
    name: str | None = Form(None),
    db: Session = Depends(get_db),
    user: User = Depends(require_role("superadmin", "admin")),
):
    from app.addons_run import install_zip

    tmp = database.STORAGE_DIR / f".addon_{secrets.token_hex(6)}.zip"
    save_upload(file.file, tmp)
    addon = install_zip(db, user.id, tmp, name=name)
    tmp.unlink(missing_ok=True)
    return {"id": addon.id, "name": addon.name, "trigger": addon.trigger, "sandbox": addon.sandbox}


@router.post("/addons/{addon_id}/run")
def run_addon_now(
    addon_id: int,
    document_id: int,
    db: Session = Depends(get_db),
    user: User = Depends(require_role("superadmin", "admin")),
):
    job = enqueue(db, "run_addon", document_id=document_id, created_by=user.id, payload={"addon_id": addon_id})
    if True:
        from app.addons_run import run_addon

        addon = db.get(Addon, addon_id)
        doc = db.get(Document, document_id)
        if not addon or not doc:
            raise HTTPException(status_code=404, detail="Addon or document not found")
        result = run_addon(db, addon, doc)
        job.status = "done" if result.get("ok") else "failed"
        job.message = json.dumps({k: result.get(k) for k in ("ok", "applied", "error")})
        db.commit()
        return result
    return {"job_id": job.id}


# ---------------------------------------------------------------------------
# Search with mode + ranking
# ---------------------------------------------------------------------------
@router.get("/search")
def power_search(
    q: str = "",
    mode: str = "all",
    skip: int = 0,
    limit: int = 100,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    parsed = parse_query(q, mode=mode)
    qry = apply_filters(_visible_docs(db, user, db.query(Document).filter(Document.deleted_at.is_(None))), parsed, db)
    ranked = False
    order_ids: list[int] = []
    if parsed.fulltext and not parsed.filters:
        hits = fts_search(parsed.fulltext, limit=1000)
        if not hits:
            ids = search_documents(parsed.fulltext, limit=1000)
            hits = [(i, float(len(ids) - n)) for n, i in enumerate(ids)]
        order_ids = [i for i, _ in hits]
        if order_ids:
            qry = qry.filter(Document.id.in_(order_ids))
            ranked = True
    rows = qry.offset(skip).limit(limit).all() if not ranked else qry.all()
    if ranked:
        pos = {i: n for n, i in enumerate(order_ids)}
        rows.sort(key=lambda d: pos.get(d.id, 10_000))
        rows = rows[skip : skip + limit]
    from app.schemas import DocumentOut

    return [DocumentOut.model_validate(r).model_dump(by_alias=True) for r in rows]


# ---------------------------------------------------------------------------
# Open ingest aliases + SMTP push + public query share
# ---------------------------------------------------------------------------
@open_intel.post("/api/v1/open/upload/item/{token}")
@open_intel.post("/api/ingest/{token}")
def open_upload_alias(
    token: str,
    file: UploadFile = File(...),
    db: Session = Depends(get_db),
):
    from app.routers.newton import _resolve_open_token, open_upload_file

    return open_upload_file(token, file, db)


@open_intel.post("/api/ingest/smtp")
async def ingest_smtp_http(
    request: Request,
    token: str | None = Query(None),
    folder_id: int | None = Query(None),
):
    raw = await request.body()
    from app.smtp_gateway import ingest_rfc822

    ids = ingest_rfc822(raw, token=token, folder_id=folder_id)
    return {"ok": True, "ids": ids}


def _share_docs(db: Session, row: QueryShare) -> list[Document]:
    if row.publish_until and row.publish_until < now():
        raise HTTPException(status_code=410, detail="Share expired")
    if not row.enabled:
        raise HTTPException(status_code=404, detail="Share disabled")
    if row.static_ids:
        return db.query(Document).filter(Document.id.in_(row.static_ids), Document.deleted_at.is_(None)).all()
    parsed = parse_query(row.query or "")
    return apply_filters(db.query(Document).filter(Document.deleted_at.is_(None)), parsed, db).limit(200).all()


@open_intel.get("/s/{token}", response_class=HTMLResponse)
def public_share_page(token: str, request: Request, db: Session = Depends(get_db)):
    row = db.query(QueryShare).filter(QueryShare.token == token).first()
    if not row:
        raise HTTPException(status_code=404, detail="Share not found")
    if row.password_hash:
        pw = request.query_params.get("password") or ""
        if not pw or not verify_password(pw, row.password_hash):
            return HTMLResponse(
                f"""<!DOCTYPE html><html><head><meta charset="utf-8"/><title>{escape(PRODUCT_NAME)}</title>
                <meta name="viewport" content="width=device-width,initial-scale=1"/>
                <style>body{{font-family:sans-serif;max-width:28rem;margin:4rem auto;padding:1rem}}</style></head>
                <body><h1>{escape(row.name)}</h1><form><input type="password" name="password" placeholder="Password"/>
                <button>Open</button></form></body></html>"""
            )
    docs = _share_docs(db, row)
    q = request.query_params.get("q") or ""
    if q:
        parsed = parse_query(q)
        ids = {d.id for d in apply_filters(db.query(Document).filter(Document.id.in_([x.id for x in docs])), parsed, db).all()}
        docs = [d for d in docs if d.id in ids]
    items = "".join(
        f"<li><a href='/api/public-share/{token}/file/{d.id}'>{escape(d.title or d.name)}</a> "
        f"<span>{escape(d.tags or '')}</span></li>"
        for d in docs
    )
    return HTMLResponse(
        f"""<!DOCTYPE html><html><head><meta charset="utf-8"/><title>{escape(row.name)}</title>
        <meta name="viewport" content="width=device-width,initial-scale=1"/>
        <style>body{{font-family:sans-serif;max-width:40rem;margin:2rem auto;padding:1rem}}
        input{{width:100%;padding:.5rem;margin:.5rem 0}}</style></head>
        <body><h1>{escape(PRODUCT_NAME)} · {escape(row.name)}</h1>
        <form><input name="q" value="{escape(q)}" placeholder="Search this share"/><button>Search</button></form>
        <ul>{items or '<li>No items</li>'}</ul></body></html>"""
    )


@open_intel.get("/api/public-share/{token}/file/{doc_id}")
def public_share_file(token: str, doc_id: int, request: Request, db: Session = Depends(get_db)):
    row = db.query(QueryShare).filter(QueryShare.token == token).first()
    if not row:
        raise HTTPException(status_code=404, detail="Share not found")
    if row.password_hash:
        pw = request.query_params.get("password") or request.headers.get("X-Share-Password") or ""
        if not pw or not verify_password(pw, row.password_hash):
            raise HTTPException(status_code=401, detail="Password required")
    docs = _share_docs(db, row)
    d = next((x for x in docs if x.id == doc_id), None)
    if not d or not d.file_path or not Path(d.file_path).exists():
        raise HTTPException(status_code=404, detail="File not found")
    return FileResponse(d.file_path, filename=d.name)


@open_intel.get("/api/auth/oidc/login")
def oidc_login(db: Session = Depends(get_db)):
    from fastapi.responses import RedirectResponse
    from app.oidc import authorization_url, enabled

    if not enabled():
        raise HTTPException(status_code=400, detail="OIDC is not configured")
    return RedirectResponse(authorization_url(db))


@open_intel.get("/api/auth/oidc/callback")
def oidc_callback(code: str, state: str, db: Session = Depends(get_db)):
    from fastapi.responses import RedirectResponse
    from app.oidc import exchange_code
    from app.security import create_access_token
    from app.config import settings

    user = exchange_code(db, code, state)
    token = create_access_token({"sub": str(user.id)})
    resp = RedirectResponse("/")
    resp.set_cookie(
        key=settings.cookie_name,
        value=token,
        httponly=True,
        secure=settings.cookie_secure,
        samesite=settings.cookie_samesite,
        max_age=settings.access_token_expire_minutes * 60,
        path="/",
    )
    return resp
