"""NewtonEDMS fusion APIs: Docspell intelligence + LogicalDoc extras.

Contacts, tags, custom fields, bookmarks, dashboards, JOEX jobs, anonymous
uploads, mail, addons, query language, merge/multi-edit, attachments, TOTP, theme.
"""
from __future__ import annotations

import mimetypes
import secrets
import shutil
import smtplib
from datetime import timedelta
from email.message import EmailMessage
from html import escape
from pathlib import Path

from fastapi import APIRouter, Depends, File, Form, HTTPException, Query, UploadFile
from fastapi.responses import FileResponse, HTMLResponse
from sqlalchemy.orm import Session

from app import database
from app.audit import audit
from app.branding import PRODUCT_NAME
from app.crypto import decrypt_secret, encrypt_secret
from app.database import get_db, now
from app.indexing import search_documents
from app.joex import process_pending_jobs, schedule_document
from app.models import (
    Addon,
    AnonymousUpload,
    Bookmark,
    Collective,
    Contact,
    CustomField,
    CustomFieldValue,
    Dashboard,
    Document,
    DocumentAttachment,
    Folder,
    MailSettings,
    NotificationRule,
    ProcessingJob,
    Tag,
    User,
)
from app.nlp import analyze
from app.permissions import has_permission, readable_document_ids, readable_folder_ids
from app.querylang import apply_filters, parse_query
from app.schemas import (
    AddonCreate,
    AddonOut,
    AnonymousUploadCreate,
    AnonymousUploadOut,
    AttachmentOut,
    BookmarkCreate,
    BookmarkOut,
    BulkEditRequest,
    CollectiveOut,
    ContactCreate,
    ContactOut,
    CustomFieldCreate,
    CustomFieldOut,
    CustomFieldValueIn,
    DashboardCreate,
    DashboardOut,
    DocumentOut,
    JobOut,
    MailSettingsCreate,
    MailSettingsOut,
    MergeRequest,
    NotificationRuleCreate,
    NotificationRuleOut,
    QueryParseOut,
    SendMailRequest,
    SuggestOut,
    TagCreate,
    TagOut,
    ThemeUpdate,
    TotpSetupOut,
)
from app.security import get_current_user, require_role
from app.storage import doc_storage_dir, safe_filename, save_upload, validate_upload_filename
from app.totp import generate_secret, otpauth_url, verify_totp

router = APIRouter(prefix="/api", tags=["newton"])


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


# ---------------------------------------------------------------------------
# Collectives
# ---------------------------------------------------------------------------
@router.get("/collectives", response_model=list[CollectiveOut])
def list_collectives(db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    return db.query(Collective).order_by(Collective.name).all()


# ---------------------------------------------------------------------------
# Contacts (address book)
# ---------------------------------------------------------------------------
@router.get("/contacts", response_model=list[ContactOut])
def list_contacts(
    q: str | None = None,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    qry = db.query(Contact)
    if q:
        qry = qry.filter(
            Contact.name.ilike(f"%{q}%")
            | Contact.email.ilike(f"%{q}%")
            | Contact.organization.ilike(f"%{q}%")
        )
    return qry.order_by(Contact.name).all()


@router.post("/contacts", response_model=ContactOut)
def create_contact(
    payload: ContactCreate,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    c = Contact(
        name=payload.name,
        email=payload.email,
        organization=payload.organization,
        kind=payload.kind,
        notes=payload.notes,
        created_by=user.id,
        concerning_only=getattr(payload, "concerning_only", False) or False,
        websites=payload.websites or [],
        emails=payload.emails or [],
        organization_id=payload.organization_id,
        collective_id=user.collective_id,
    )
    db.add(c)
    db.commit()
    db.refresh(c)
    audit(db, user, "CONTACT_CREATE", "contact", c.id, c.name)
    return c


@router.put("/contacts/{contact_id}", response_model=ContactOut)
def update_contact(
    contact_id: int,
    payload: ContactCreate,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    c = db.get(Contact, contact_id)
    if not c:
        raise HTTPException(status_code=404, detail="Contact not found")
    c.name = payload.name
    c.email = payload.email
    c.organization = payload.organization
    c.kind = payload.kind
    c.notes = payload.notes
    c.concerning_only = getattr(payload, "concerning_only", False) or False
    c.websites = payload.websites or []
    c.emails = payload.emails or []
    c.organization_id = payload.organization_id
    db.commit()
    db.refresh(c)
    return c


@router.delete("/contacts/{contact_id}")
def delete_contact(
    contact_id: int,
    db: Session = Depends(get_db),
    user: User = Depends(require_role("superadmin", "admin", "manager")),
):
    c = db.get(Contact, contact_id)
    if not c:
        raise HTTPException(status_code=404, detail="Contact not found")
    db.query(Document).filter(Document.correspondent_id == contact_id).update({"correspondent_id": None})
    db.query(Document).filter(Document.concerning_id == contact_id).update({"concerning_id": None})
    db.delete(c)
    db.commit()
    return {"ok": True}


# ---------------------------------------------------------------------------
# Tag catalog
# ---------------------------------------------------------------------------
@router.get("/tags", response_model=list[TagOut])
def list_tags(db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    return db.query(Tag).order_by(Tag.name).all()


@router.post("/tags", response_model=TagOut)
def create_tag(
    payload: TagCreate,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    name = payload.name.strip()
    if not name:
        raise HTTPException(status_code=400, detail="Tag name required")
    existing = db.query(Tag).filter(Tag.name == name).first()
    if existing:
        return existing
    t = Tag(name=name, category=payload.category, created_by=user.id)
    db.add(t)
    db.commit()
    db.refresh(t)
    return t


@router.delete("/tags/{tag_id}")
def delete_tag(
    tag_id: int,
    db: Session = Depends(get_db),
    user: User = Depends(require_role("superadmin", "admin", "manager")),
):
    t = db.get(Tag, tag_id)
    if not t:
        raise HTTPException(status_code=404, detail="Tag not found")
    db.delete(t)
    db.commit()
    return {"ok": True}


# ---------------------------------------------------------------------------
# Custom fields
# ---------------------------------------------------------------------------
@router.get("/custom-fields", response_model=list[CustomFieldOut])
def list_custom_fields(db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    return db.query(CustomField).order_by(CustomField.name).all()


@router.post("/custom-fields", response_model=CustomFieldOut)
def create_custom_field(
    payload: CustomFieldCreate,
    db: Session = Depends(get_db),
    user: User = Depends(require_role("superadmin", "admin", "manager")),
):
    if db.query(CustomField).filter(CustomField.name == payload.name).first():
        raise HTTPException(status_code=400, detail="Field name already exists")
    f = CustomField(
        name=payload.name,
        label=payload.label or payload.name,
        ftype=payload.ftype,
        required=payload.required,
        created_by=user.id,
    )
    db.add(f)
    db.commit()
    db.refresh(f)
    return f


@router.delete("/custom-fields/{field_id}")
def delete_custom_field(
    field_id: int,
    db: Session = Depends(get_db),
    user: User = Depends(require_role("superadmin", "admin", "manager")),
):
    f = db.get(CustomField, field_id)
    if not f:
        raise HTTPException(status_code=404, detail="Field not found")
    db.query(CustomFieldValue).filter(CustomFieldValue.field_id == field_id).delete()
    db.delete(f)
    db.commit()
    return {"ok": True}


@router.get("/documents/{doc_id}/fields")
def get_doc_fields(
    doc_id: int,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    d = db.get(Document, doc_id)
    if not d:
        raise HTTPException(status_code=404, detail="Document not found")
    values = db.query(CustomFieldValue).filter(CustomFieldValue.document_id == doc_id).all()
    return [{"field_id": v.field_id, "value": v.value} for v in values]


@router.put("/documents/{doc_id}/fields")
def set_doc_fields(
    doc_id: int,
    payload: list[CustomFieldValueIn],
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    d = db.get(Document, doc_id)
    if not d:
        raise HTTPException(status_code=404, detail="Document not found")
    f = db.get(Folder, d.folder_id)
    if not has_permission(db, user, "write", f, d):
        raise HTTPException(status_code=403, detail="No permission")
    db.query(CustomFieldValue).filter(CustomFieldValue.document_id == doc_id).delete()
    for item in payload:
        db.add(CustomFieldValue(field_id=item.field_id, document_id=doc_id, value=item.value))
    db.commit()
    return {"ok": True}


# ---------------------------------------------------------------------------
# Query language + suggestions
# ---------------------------------------------------------------------------
@router.get("/query/parse", response_model=QueryParseOut)
def parse_q(q: str = "", user: User = Depends(get_current_user)):
    parsed = parse_query(q)
    return {"filters": parsed.filters, "fulltext": parsed.fulltext, "raw": parsed.raw}


@router.get("/query", response_model=list[DocumentOut])
def run_query(
    q: str = "",
    mode: str = Query("all"),
    skip: int = Query(0, ge=0),
    limit: int = Query(100, le=500),
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    parsed = parse_query(q, mode=mode)
    qry = db.query(Document).filter(Document.deleted_at.is_(None))
    qry = apply_filters(qry, parsed, db)
    ranked_ids: list[int] = []
    if parsed.fulltext:
        like = f"%{parsed.fulltext}%"
        from app.fts import search as fts_search
        from sqlalchemy import or_

        hits = fts_search(parsed.fulltext, limit=1000)
        ids = [i for i, _ in hits] or search_documents(parsed.fulltext, limit=1000)
        ranked_ids = ids
        if mode == "names":
            conds = [Document.name.ilike(like), Document.title.ilike(like)]
        elif mode == "contents":
            conds = [Document.extracted_text.ilike(like), Document.notes.ilike(like)]
        else:
            conds = [
                Document.name.ilike(like),
                Document.title.ilike(like),
                Document.tags.ilike(like),
                Document.notes.ilike(like),
                Document.extracted_text.ilike(like),
            ]
        if ids:
            conds.append(Document.id.in_(ids))
        qry = qry.filter(or_(*conds))
    qry = _visible_docs(db, user, qry)
    if ranked_ids and parsed.fulltext and not parsed.filters:
        rows = qry.all()
        pos = {i: n for n, i in enumerate(ranked_ids)}
        rows.sort(key=lambda d: pos.get(d.id, 10_000))
        return rows[skip : skip + limit]
    return qry.order_by(Document.updated_at.desc()).offset(skip).limit(limit).all()


@router.get("/documents/{doc_id}/suggest", response_model=SuggestOut)
def suggest_metadata(
    doc_id: int,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    d = db.get(Document, doc_id)
    if not d:
        raise HTTPException(status_code=404, detail="Document not found")
    hints = analyze(db, d.extracted_text or d.title or d.name)
    return {
        "tags": hints["tags"],
        "contacts": hints["contacts"],
        "dates": hints["dates"],
        "language": hints["language"],
    }


@router.get("/documents/{doc_id}/text")
def get_extracted_text(
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
    return {"text": d.extracted_text or "", "processing_status": d.processing_status}


@router.get("/documents/{doc_id}/duplicates", response_model=list[DocumentOut])
def list_duplicates(
    doc_id: int,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    d = db.get(Document, doc_id)
    if not d or not d.content_hash:
        return []
    twins = db.query(Document).filter(Document.content_hash == d.content_hash, Document.id != d.id).all()
    return twins


# ---------------------------------------------------------------------------
# Attachments
# ---------------------------------------------------------------------------
@router.get("/documents/{doc_id}/attachments", response_model=list[AttachmentOut])
def list_attachments(
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
    return db.query(DocumentAttachment).filter(DocumentAttachment.document_id == doc_id).all()


@router.post("/documents/{doc_id}/attachments", response_model=AttachmentOut)
def add_attachment(
    doc_id: int,
    file: UploadFile = File(...),
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    d = db.get(Document, doc_id)
    if not d:
        raise HTTPException(status_code=404, detail="Document not found")
    f = db.get(Folder, d.folder_id)
    if not has_permission(db, user, "write", f, d):
        raise HTTPException(status_code=403, detail="No permission")
    name = safe_filename(file.filename)
    validate_upload_filename(name)
    dest = doc_storage_dir(d.id) / "attachments"
    dest.mkdir(exist_ok=True)
    path = dest / name
    size = save_upload(file.file, path)
    att = DocumentAttachment(
        document_id=d.id,
        name=name,
        file_path=str(path),
        size=size,
        mime=file.content_type or mimetypes.guess_type(name)[0],
        role="original",
    )
    db.add(att)
    db.commit()
    db.refresh(att)
    return att


@router.get("/documents/{doc_id}/attachments/{att_id}/download")
def download_attachment(
    doc_id: int,
    att_id: int,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    d = db.get(Document, doc_id)
    if not d:
        raise HTTPException(status_code=404, detail="Document not found")
    f = db.get(Folder, d.folder_id)
    if not has_permission(db, user, "read", f, d):
        raise HTTPException(status_code=403, detail="No permission")
    att = db.get(DocumentAttachment, att_id)
    if not att or att.document_id != doc_id:
        raise HTTPException(status_code=404, detail="Attachment not found")
    path = Path(att.file_path)
    if not path.exists():
        raise HTTPException(status_code=404, detail="File missing")
    return FileResponse(path, filename=att.name, media_type=att.mime)


@router.get("/documents/{doc_id}/original")
def download_original(
    doc_id: int,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    """Download the untouched original (Docspell non-destructive storage)."""
    d = db.get(Document, doc_id)
    if not d:
        raise HTTPException(status_code=404, detail="Document not found")
    f = db.get(Folder, d.folder_id)
    if not has_permission(db, user, "read", f, d):
        raise HTTPException(status_code=403, detail="No permission")
    path = Path(d.original_file_path or d.file_path)
    if not path.exists():
        raise HTTPException(status_code=404, detail="Original missing")
    return FileResponse(path, filename=d.name, media_type=d.mime)


# ---------------------------------------------------------------------------
# Merge + multi-edit
# ---------------------------------------------------------------------------
@router.post("/documents/merge", response_model=DocumentOut)
def merge_documents(
    payload: MergeRequest,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    if len(payload.ids) < 2:
        raise HTTPException(status_code=400, detail="Need at least two documents to merge")
    docs = [db.get(Document, i) for i in payload.ids]
    if any(d is None for d in docs):
        raise HTTPException(status_code=404, detail="One or more documents not found")
    folder_id = payload.folder_id or docs[0].folder_id
    folder = db.get(Folder, folder_id)
    if not folder or not has_permission(db, user, "write", folder):
        raise HTTPException(status_code=403, detail="No permission")
    title = payload.title or f"Merged: {docs[0].title}"
    dest_dir = database.STORAGE_DIR / f"merge_{secrets.token_hex(8)}"
    dest_dir.mkdir(parents=True, exist_ok=True)
    from app.convert import merge_pdfs

    ordered_atts = []
    if payload.attachment_ids:
        for aid in payload.attachment_ids:
            att = db.get(DocumentAttachment, aid)
            if att and Path(att.file_path).exists():
                ordered_atts.append(Path(att.file_path))
    if ordered_atts:
        sources = ordered_atts
    else:
        sources = [Path(d.pdf_file_path or d.file_path) for d in docs if d.file_path]
    merged_pdf = dest_dir / "merged.pdf"
    try:
        merge_pdfs(sources, merged_pdf)
        name = "merged.pdf"
        mime = "application/pdf"
        tmp = merged_pdf
    except Exception:
        parts = []
        for src in sources:
            if src.exists():
                parts.append(src.read_bytes())
        blob = b"\n\n".join(parts) if all(d.mime and d.mime.startswith("text/") for d in docs) else b"".join(parts)
        name = "merged.txt" if all(d.mime and "text" in (d.mime or "") for d in docs) else "merged.bin"
        tmp = dest_dir / name
        tmp.write_bytes(blob)
        mime = "text/plain" if name.endswith(".txt") else "application/octet-stream"
    merged = Document(
        name=name,
        title=title,
        folder_id=folder_id,
        tags=",".join(sorted({t.strip() for d in docs for t in (d.tags or "").split(",") if t.strip()})),
        metadata_json={"merged_from": payload.ids},
        created_by=user.id,
        size=tmp.stat().st_size,
        mime=mime,
        file_path=str(tmp),
        source="merge",
        processing_status="pending",
        notes="\n\n".join(d.notes or "" for d in docs if d.notes),
    )
    db.add(merged)
    db.flush()
    final_dir = doc_storage_dir(merged.id)
    final = final_dir / name
    shutil.move(str(tmp), str(final))
    shutil.rmtree(dest_dir, ignore_errors=True)
    merged.file_path = str(final)
    for d in docs:
        src = Path(d.file_path)
        if src.exists():
            att_dir = final_dir / "attachments"
            att_dir.mkdir(exist_ok=True)
            att_path = att_dir / f"{d.id}_{safe_filename(d.name)}"
            shutil.copy2(src, att_path)
            db.add(
                DocumentAttachment(
                    document_id=merged.id,
                    name=d.name,
                    file_path=str(att_path),
                    size=d.size,
                    mime=d.mime,
                    role="extracted",
                )
            )
    db.commit()
    db.refresh(merged)
    schedule_document(db, merged.id, created_by=user.id)
    audit(db, user, "DOCUMENT_MERGE", "document", merged.id, f"Merged {payload.ids}")
    return merged


@router.post("/documents/bulk-edit")
def bulk_edit(
    payload: BulkEditRequest,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    updated = 0
    for doc_id in payload.ids:
        d = db.get(Document, doc_id)
        if not d:
            continue
        f = db.get(Folder, d.folder_id)
        if not has_permission(db, user, "write", f, d):
            continue
        if payload.tags is not None:
            d.tags = payload.tags
        if payload.folder_id is not None:
            d.folder_id = payload.folder_id
        if payload.status is not None:
            d.status = payload.status
        if payload.correspondent_id is not None:
            d.correspondent_id = payload.correspondent_id
        if payload.concerning_id is not None:
            d.concerning_id = payload.concerning_id
        if payload.due_date is not None:
            d.due_date = payload.due_date
        if payload.notes is not None:
            d.notes = payload.notes
        d.updated_at = now()
        updated += 1
    db.commit()
    audit(db, user, "DOCUMENT_BULK_EDIT", "document", None, f"Updated {updated} documents")
    return {"ok": True, "updated": updated}


# ---------------------------------------------------------------------------
# Bookmarks
# ---------------------------------------------------------------------------
@router.get("/bookmarks", response_model=list[BookmarkOut])
def list_bookmarks(db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    return db.query(Bookmark).filter(Bookmark.user_id == user.id).order_by(Bookmark.name).all()


@router.post("/bookmarks", response_model=BookmarkOut)
def create_bookmark(
    payload: BookmarkCreate,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    b = Bookmark(name=payload.name, query=payload.query or "", user_id=user.id, kind=getattr(payload, "kind", "query") or "query", resource_id=getattr(payload, "resource_id", None))
    db.add(b)
    db.commit()
    db.refresh(b)
    return b


@router.delete("/bookmarks/{bookmark_id}")
def delete_bookmark(
    bookmark_id: int,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    b = db.get(Bookmark, bookmark_id)
    if not b or b.user_id != user.id:
        raise HTTPException(status_code=404, detail="Bookmark not found")
    db.delete(b)
    db.commit()
    return {"ok": True}


# ---------------------------------------------------------------------------
# Dashboards
# ---------------------------------------------------------------------------
@router.get("/dashboards", response_model=list[DashboardOut])
def list_dashboards(db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    return db.query(Dashboard).filter(Dashboard.user_id == user.id).all()


@router.get("/dashboards/home")
def home_dashboard(db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    """Aggregated home widgets: custom board when present, else built-in dashlets."""
    board = (
        db.query(Dashboard)
        .filter(Dashboard.user_id == user.id, Dashboard.is_default.is_(True))
        .first()
        or db.query(Dashboard).filter(Dashboard.user_id == user.id).first()
    )
    recent = _visible_docs(db, user, db.query(Document).filter(Document.deleted_at.is_(None))).order_by(Document.updated_at.desc()).limit(10).all()
    overdue = (
        _visible_docs(db, user, db.query(Document).filter(Document.deleted_at.is_(None)))
        .filter(Document.due_date.isnot(None), Document.due_date < now())
        .limit(10)
        .all()
    )
    inbox = (
        _visible_docs(db, user, db.query(Document).filter(Document.deleted_at.is_(None)))
        .filter(Document.processing_status != "done")
        .limit(10)
        .all()
    )
    jobs = db.query(ProcessingJob).order_by(ProcessingJob.id.desc()).limit(10).all()

    def _brief(d: Document) -> dict:
        return {
            "id": d.id,
            "title": d.title,
            "name": d.name,
            "status": d.status,
            "kind": None,
            "document_id": d.id,
            "thumbnail": f"/api/documents/{d.id}/thumbnail" if d.thumbnail_path else None,
            "confirmed": bool(d.confirmed),
        }

    payload = {
        "recent": [_brief(d) for d in recent],
        "overdue": [_brief(d) for d in overdue],
        "inbox": [_brief(d) for d in inbox],
        "jobs": [
            {
                "id": j.id,
                "kind": j.kind,
                "status": j.status,
                "document_id": j.document_id,
                "title": j.kind,
                "message": j.message,
            }
            for j in jobs
        ],
        "board": None,
    }
    if board and board.layout:
        payload["board"] = {
            "id": board.id,
            "name": board.name,
            "layout": board.layout,
            "scope": board.scope,
        }
    return payload


@router.post("/dashboards", response_model=DashboardOut)
def create_dashboard(
    payload: DashboardCreate,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    d = Dashboard(
        name=payload.name,
        layout=payload.layout or [],
        is_default=payload.is_default,
        user_id=user.id,
    )
    db.add(d)
    db.commit()
    db.refresh(d)
    return d


@router.delete("/dashboards/{dashboard_id}")
def delete_dashboard(
    dashboard_id: int,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    d = db.get(Dashboard, dashboard_id)
    if not d or d.user_id != user.id:
        raise HTTPException(status_code=404, detail="Dashboard not found")
    db.delete(d)
    db.commit()
    return {"ok": True}


# ---------------------------------------------------------------------------
# JOEX jobs
# ---------------------------------------------------------------------------
@router.get("/jobs", response_model=list[JobOut])
def list_jobs(
    status: str | None = None,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    q = db.query(ProcessingJob)
    if status:
        q = q.filter(ProcessingJob.status == status)
    return q.order_by(ProcessingJob.id.desc()).limit(200).all()


@router.post("/jobs/{job_id}/cancel")
def cancel_job(
    job_id: int,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    job = db.get(ProcessingJob, job_id)
    if not job:
        raise HTTPException(status_code=404, detail="Job not found")
    if job.status not in ("queued", "running"):
        raise HTTPException(status_code=400, detail="Job cannot be cancelled")
    job.status = "cancelled"
    job.finished_at = now()
    db.commit()
    return {"ok": True}


@router.post("/jobs/{job_id}/priority")
def set_priority(
    job_id: int,
    priority: int = 0,
    db: Session = Depends(get_db),
    user: User = Depends(require_role("superadmin", "admin")),
):
    job = db.get(ProcessingJob, job_id)
    if not job:
        raise HTTPException(status_code=404, detail="Job not found")
    job.priority = priority
    db.commit()
    return {"ok": True, "priority": job.priority}


@router.post("/jobs/run")
def run_jobs(
    limit: int = 5,
    user: User = Depends(require_role("superadmin", "admin")),
):
    n = process_pending_jobs(limit=limit)
    return {"processed": n}


@router.post("/documents/{doc_id}/reprocess")
def reprocess_document(
    doc_id: int,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    d = db.get(Document, doc_id)
    if not d:
        raise HTTPException(status_code=404, detail="Document not found")
    d.processing_status = "pending"
    db.commit()
    job = schedule_document(db, d.id, created_by=user.id)
    return {"ok": True, "job_id": job.id}


# ---------------------------------------------------------------------------
# Anonymous upload URLs
# ---------------------------------------------------------------------------
@router.get("/open-uploads", response_model=list[AnonymousUploadOut])
def list_open_uploads(db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    rows = db.query(AnonymousUpload).filter(AnonymousUpload.created_by == user.id).all()
    return [_open_out(r) for r in rows]


@router.post("/open-uploads", response_model=AnonymousUploadOut)
def create_open_upload(
    payload: AnonymousUploadCreate,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    folder = db.get(Folder, payload.folder_id)
    if not folder or not has_permission(db, user, "write", folder):
        raise HTTPException(status_code=403, detail="No permission on folder")
    expires = now() + timedelta(days=payload.expires_days) if payload.expires_days else None
    row = AnonymousUpload(
        token=secrets.token_urlsafe(24),
        name=payload.name,
        folder_id=payload.folder_id,
        tags=payload.tags,
        correspondent_id=payload.correspondent_id,
        max_files=payload.max_files,
        created_by=user.id,
        expires_at=expires,
        skip_duplicates=getattr(payload, "skip_duplicates", False) or False,
        priority=getattr(payload, "priority", 0) or 0,
        language=getattr(payload, "language", None),
    )
    db.add(row)
    db.commit()
    db.refresh(row)
    audit(db, user, "OPEN_UPLOAD_CREATE", "anonymous_upload", row.id, row.name)
    return _open_out(row)


@router.delete("/open-uploads/{upload_id}")
def delete_open_upload(
    upload_id: int,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    row = db.get(AnonymousUpload, upload_id)
    if not row or (row.created_by != user.id and user.role not in ("superadmin", "admin")):
        raise HTTPException(status_code=404, detail="Upload URL not found")
    db.delete(row)
    db.commit()
    return {"ok": True}


def _open_out(row: AnonymousUpload) -> dict:
    return {
        "id": row.id,
        "token": row.token,
        "name": row.name,
        "folder_id": row.folder_id,
        "tags": row.tags,
        "correspondent_id": row.correspondent_id,
        "enabled": row.enabled,
        "max_files": row.max_files,
        "upload_count": row.upload_count,
        "created_by": row.created_by,
        "created_at": row.created_at,
        "expires_at": row.expires_at,
        "url": f"/u/{row.token}",
        "skip_duplicates": getattr(row, "skip_duplicates", False),
        "priority": getattr(row, "priority", 0),
        "language": getattr(row, "language", None),
    }


# ---------------------------------------------------------------------------
# Mail settings + send
# ---------------------------------------------------------------------------
@router.get("/mail-settings", response_model=list[MailSettingsOut])
def list_mail(db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    return db.query(MailSettings).filter(MailSettings.user_id == user.id).all()


@router.post("/mail-settings", response_model=MailSettingsOut)
def create_mail(
    payload: MailSettingsCreate,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    row = MailSettings(
        user_id=user.id,
        kind=payload.kind,
        name=payload.name,
        host=payload.host,
        port=payload.port,
        username=payload.username,
        password_enc=encrypt_secret(payload.password or ""),
        use_ssl=payload.use_ssl,
        mailbox=payload.mailbox,
    )
    db.add(row)
    db.commit()
    db.refresh(row)
    return row


@router.delete("/mail-settings/{settings_id}")
def delete_mail(
    settings_id: int,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    row = db.get(MailSettings, settings_id)
    if not row or row.user_id != user.id:
        raise HTTPException(status_code=404, detail="Settings not found")
    db.delete(row)
    db.commit()
    return {"ok": True}


@router.post("/mail/send")
def send_mail(
    payload: SendMailRequest,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    smtp = None
    if payload.settings_id:
        smtp = db.get(MailSettings, payload.settings_id)
        if not smtp or smtp.user_id != user.id or smtp.kind != "smtp":
            raise HTTPException(status_code=404, detail="SMTP settings not found")
    else:
        smtp = db.query(MailSettings).filter(MailSettings.user_id == user.id, MailSettings.kind == "smtp").first()
    if not smtp:
        raise HTTPException(status_code=400, detail="Configure SMTP settings first")
    subject = payload.subject
    body = payload.body or f"Documents from {PRODUCT_NAME}"
    if payload.template_id:
        from app.models import MailTemplate

        tpl = db.get(MailTemplate, payload.template_id)
        if tpl and tpl.user_id == user.id:
            subject = tpl.subject or subject
            body = tpl.body or body
    msg = EmailMessage()
    msg["Subject"] = subject
    msg["From"] = smtp.username or user.email or "newtonedms@localhost"
    msg["To"] = payload.to
    if getattr(payload, "cc", None):
        msg["Cc"] = payload.cc
    msg.set_content(body)
    for doc_id in payload.document_ids:
        d = db.get(Document, doc_id)
        if not d:
            continue
        f = db.get(Folder, d.folder_id)
        if not has_permission(db, user, "read", f, d):
            continue
        use_pdf = payload.attach_pdf and d.pdf_file_path and Path(d.pdf_file_path).exists()
        path = Path(d.pdf_file_path) if use_pdf else Path(d.file_path)
        mime = "application/pdf" if use_pdf else (d.mime or "application/octet-stream")
        fname = Path(d.pdf_file_path).name if use_pdf else d.name
        if path.exists():
            msg.add_attachment(
                path.read_bytes(),
                maintype=mime.split("/")[0],
                subtype=mime.split("/")[-1],
                filename=fname,
            )
    password = decrypt_secret(smtp.password_enc)
    try:
        if smtp.use_ssl and smtp.port == 465:
            with smtplib.SMTP_SSL(smtp.host, smtp.port, timeout=20) as client:
                if smtp.username:
                    client.login(smtp.username, password)
                client.send_message(msg)
        else:
            with smtplib.SMTP(smtp.host, smtp.port, timeout=20) as client:
                client.starttls()
                if smtp.username:
                    client.login(smtp.username, password)
                client.send_message(msg)
    except Exception as exc:
        raise HTTPException(status_code=502, detail=f"SMTP send failed: {exc}") from exc
    audit(db, user, "MAIL_SEND", "document", None, f"to={payload.to} docs={payload.document_ids}")
    return {"ok": True}


# ---------------------------------------------------------------------------
# Notification rules + addons
# ---------------------------------------------------------------------------
@router.get("/notification-rules", response_model=list[NotificationRuleOut])
def list_rules(db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    return db.query(NotificationRule).filter(NotificationRule.user_id == user.id).all()


@router.post("/notification-rules", response_model=NotificationRuleOut)
def create_rule(
    payload: NotificationRuleCreate,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    r = NotificationRule(
        user_id=user.id,
        name=payload.name,
        query=payload.query,
        channel=payload.channel,
        interval_hours=payload.interval_hours,
    )
    db.add(r)
    db.commit()
    db.refresh(r)
    return r


@router.delete("/notification-rules/{rule_id}")
def delete_rule(
    rule_id: int,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    r = db.get(NotificationRule, rule_id)
    if not r or r.user_id != user.id:
        raise HTTPException(status_code=404, detail="Rule not found")
    db.delete(r)
    db.commit()
    return {"ok": True}


@router.get("/addons", response_model=list[AddonOut])
def list_addons(db: Session = Depends(get_db), user: User = Depends(require_role("superadmin", "admin"))):
    return db.query(Addon).all()


@router.post("/addons", response_model=AddonOut)
def create_addon(
    payload: AddonCreate,
    db: Session = Depends(get_db),
    user: User = Depends(require_role("superadmin", "admin")),
):
    a = Addon(
        name=payload.name,
        event=payload.event,
        webhook_url=payload.webhook_url,
        created_by=user.id,
    )
    db.add(a)
    db.commit()
    db.refresh(a)
    return a


@router.delete("/addons/{addon_id}")
def delete_addon(
    addon_id: int,
    db: Session = Depends(get_db),
    user: User = Depends(require_role("superadmin", "admin")),
):
    a = db.get(Addon, addon_id)
    if not a:
        raise HTTPException(status_code=404, detail="Addon not found")
    db.delete(a)
    db.commit()
    return {"ok": True}


# ---------------------------------------------------------------------------
# TOTP + theme
# ---------------------------------------------------------------------------
@router.post("/auth/totp/setup", response_model=TotpSetupOut)
def totp_setup(db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    secret = generate_secret()
    user.totp_secret = secret
    user.totp_enabled = False
    db.commit()
    return {
        "secret": secret,
        "otpauth_url": otpauth_url(secret, user.username),
        "enabled": False,
    }


@router.post("/auth/totp/enable")
def totp_enable(
    code: str = Form(...),
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    if not user.totp_secret or not verify_totp(user.totp_secret, code):
        raise HTTPException(status_code=400, detail="Invalid TOTP code")
    user.totp_enabled = True
    db.commit()
    audit(db, user, "TOTP_ENABLE", "user", user.id, "Two-factor authentication enabled")
    return {"ok": True}


@router.post("/auth/totp/disable")
def totp_disable(
    code: str = Form(...),
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    if user.totp_enabled and not verify_totp(user.totp_secret or "", code):
        raise HTTPException(status_code=400, detail="Invalid TOTP code")
    user.totp_enabled = False
    user.totp_secret = None
    db.commit()
    return {"ok": True}


@router.put("/auth/theme")
def set_theme(
    payload: ThemeUpdate,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    user.theme = payload.theme
    db.commit()
    return {"ok": True, "theme": user.theme}


# ---------------------------------------------------------------------------
# Public anonymous upload (no auth)
# ---------------------------------------------------------------------------
open_router = APIRouter(tags=["open"])


def _resolve_open_token(db: Session, token: str) -> AnonymousUpload:
    row = db.query(AnonymousUpload).filter(AnonymousUpload.token == token).first()
    if not row or not row.enabled:
        raise HTTPException(status_code=404, detail="Upload URL not found")
    if row.expires_at and row.expires_at < now():
        raise HTTPException(status_code=410, detail="Upload URL expired")
    if row.upload_count >= row.max_files:
        raise HTTPException(status_code=410, detail="Upload URL quota reached")
    return row


@open_router.get("/u/{token}", response_class=HTMLResponse)
def open_upload_page(token: str, db: Session = Depends(get_db)):
    row = _resolve_open_token(db, token)
    return HTMLResponse(
        f"""<!DOCTYPE html><html><head><meta charset="utf-8"/><title>{PRODUCT_NAME} upload</title>
        <style>body{{font-family:sans-serif;max-width:28rem;margin:4rem auto;padding:1rem}}
        input,button{{display:block;width:100%;margin:.5rem 0;padding:.5rem}}</style></head>
        <body><h1>{escape(PRODUCT_NAME)}</h1><p>Upload to <b>{escape(row.name)}</b></p>
        <form method="post" action="/api/open/{token}" enctype="multipart/form-data">
        <input type="file" name="file" required />
        <button type="submit">Upload</button></form></body></html>"""
    )


@open_router.post("/api/open/{token}")
def open_upload_file(
    token: str,
    file: UploadFile = File(...),
    db: Session = Depends(get_db),
) -> dict:
    row = _resolve_open_token(db, token)
    folder = db.get(Folder, row.folder_id)
    if not folder:
        raise HTTPException(status_code=404, detail="Target folder missing")
    owner = db.get(User, row.created_by)
    name = safe_filename(file.filename)
    validate_upload_filename(name)
    tmp = database.STORAGE_DIR / f".open_{secrets.token_hex(8)}"
    size = save_upload(file.file, tmp)
    from app.hashing import file_sha256

    digest = file_sha256(tmp)
    if row.skip_duplicates and db.query(Document).filter(Document.content_hash == digest).first():
        tmp.unlink(missing_ok=True)
        return {"ok": True, "skipped": True, "reason": "duplicate"}
    d = Document(
        name=name,
        title=name,
        folder_id=folder.id,
        tags=row.tags or "",
        created_by=owner.id if owner else row.created_by,
        size=size,
        mime=file.content_type or mimetypes.guess_type(name)[0],
        file_path=str(tmp),
        source="anonymous",
        source_id=row.id,
        correspondent_id=row.correspondent_id,
        language=row.language,
        processing_status="pending",
        content_hash=digest,
        confirmed=False,
    )
    db.add(d)
    db.flush()
    dest = doc_storage_dir(d.id) / f"v1{Path(name).suffix}"
    shutil.move(str(tmp), str(dest))
    d.file_path = str(dest)
    row.upload_count = (row.upload_count or 0) + 1
    db.commit()
    db.refresh(d)
    schedule_document(db, d.id, created_by=row.created_by)
    return {"ok": True, "id": d.id, "name": d.name}
