"""Collaboration and governance routes: templates, comments, shares, retention, reports."""
from __future__ import annotations

import secrets
import shutil
from datetime import timedelta
from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import FileResponse
from sqlalchemy import func, or_
from sqlalchemy.orm import Session

from app.audit import audit
from app.config import settings
from app.database import get_db, now
from app.indexing import remove_document
from app.limiter import limiter
from app.models import (
    AuditLog,
    CalendarEvent,
    Comment,
    Document,
    DocumentVersion,
    Folder,
    Group,
    MetadataTemplate,
    RetentionPolicy,
    ShareLink,
    Task,
    User,
    WorkflowInstance,
)
from app.permissions import has_permission
from app.schemas import (
    CommentCreate,
    CommentOut,
    MetadataTemplateCreate,
    MetadataTemplateOut,
    ReportSummary,
    RetentionPolicyCreate,
    RetentionPolicyOut,
    ShareLinkOut,
)
from app.security import get_current_user, require_role
from app.storage import doc_storage_dir

router = APIRouter(prefix="/api", tags=["collaboration"])

# ---------------------------------------------------------------------------
# Metadata templates
# ---------------------------------------------------------------------------
@router.get("/metadata-templates", response_model=list[MetadataTemplateOut])
def list_templates(
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    return db.query(MetadataTemplate).order_by(MetadataTemplate.name).all()


@router.post("/metadata-templates", response_model=MetadataTemplateOut)
def create_template(
    payload: MetadataTemplateCreate,
    db: Session = Depends(get_db),
    user: User = Depends(require_role("superadmin", "admin", "manager")),
):
    if db.query(MetadataTemplate).filter(MetadataTemplate.name == payload.name).first():
        raise HTTPException(status_code=400, detail="Template name already exists")
    t = MetadataTemplate(
        name=payload.name,
        description=payload.description,
        fields=payload.fields or [],
        created_by=user.id,
    )
    db.add(t)
    db.commit()
    db.refresh(t)
    audit(db, user, "METADATA_TEMPLATE_CREATE", "metadata_template", t.id, t.name)
    return t


@router.delete("/metadata-templates/{template_id}")
def delete_template(
    template_id: int,
    db: Session = Depends(get_db),
    user: User = Depends(require_role("superadmin", "admin")),
):
    t = db.get(MetadataTemplate, template_id)
    if not t:
        raise HTTPException(status_code=404, detail="Template not found")
    db.delete(t)
    db.commit()
    audit(db, user, "METADATA_TEMPLATE_DELETE", "metadata_template", template_id, t.name)
    return {"ok": True}


# ---------------------------------------------------------------------------
# Comments / annotations
# ---------------------------------------------------------------------------
@router.get("/documents/{doc_id}/comments", response_model=list[CommentOut])
def list_comments(
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
    comments = (
        db.query(Comment, User.username)
        .join(User, Comment.user_id == User.id)
        .filter(Comment.document_id == doc_id)
        .order_by(Comment.created_at)
        .all()
    )
    result = []
    for c, username in comments:
        result.append({
            "id": c.id,
            "document_id": c.document_id,
            "user_id": c.user_id,
            "username": username,
            "text": c.text,
            "page": c.page,
            "x": c.x,
            "y": c.y,
            "created_at": c.created_at,
        })
    return result


@router.post("/documents/{doc_id}/comments", response_model=CommentOut)
def add_comment(
    doc_id: int,
    payload: CommentCreate,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    d = db.get(Document, doc_id)
    if not d:
        raise HTTPException(status_code=404, detail="Document not found")
    f = db.get(Folder, d.folder_id)
    if not has_permission(db, user, "read", f, d):
        raise HTTPException(status_code=403, detail="No permission")
    c = Comment(
        document_id=doc_id,
        user_id=user.id,
        text=payload.text,
        page=payload.page,
        x=payload.x,
        y=payload.y,
    )
    db.add(c)
    db.commit()
    db.refresh(c)
    audit(db, user, "COMMENT_CREATE", "comment", c.id, f"Document {doc_id}")
    return {
        "id": c.id,
        "document_id": c.document_id,
        "user_id": c.user_id,
        "username": user.username,
        "text": c.text,
        "page": c.page,
        "x": c.x,
        "y": c.y,
        "created_at": c.created_at,
    }


@router.delete("/documents/{doc_id}/comments/{comment_id}")
def delete_comment(
    doc_id: int,
    comment_id: int,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    c = db.get(Comment, comment_id)
    if not c or c.document_id != doc_id:
        raise HTTPException(status_code=404, detail="Comment not found")
    if c.user_id != user.id and user.role not in ("superadmin", "admin"):
        raise HTTPException(status_code=403, detail="Not your comment")
    # The caller must still be able to read the document (access may have been
    # revoked since the comment was written).
    d = db.get(Document, doc_id)
    if not d:
        raise HTTPException(status_code=404, detail="Document not found")
    f = db.get(Folder, d.folder_id)
    if not has_permission(db, user, "read", f, d):
        raise HTTPException(status_code=403, detail="No permission")
    db.delete(c)
    db.commit()
    audit(db, user, "COMMENT_DELETE", "comment", comment_id, f"Document {doc_id}")
    return {"ok": True}


# ---------------------------------------------------------------------------
# Share links
# ---------------------------------------------------------------------------
@router.post("/documents/{doc_id}/shares", response_model=ShareLinkOut)
def create_share(
    doc_id: int,
    expires_days: int | None = None,
    max_downloads: int | None = None,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    d = db.get(Document, doc_id)
    if not d:
        raise HTTPException(status_code=404, detail="Document not found")
    f = db.get(Folder, d.folder_id)
    # Sharing mints an unauthenticated download URL, so require write access —
    # a read-only viewer must not be able to create permanent ACL bypasses.
    if not has_permission(db, user, "write", f, d):
        raise HTTPException(status_code=403, detail="No permission to share")
    # Shares always expire (default 7 days) so they cannot outlive the grant.
    expires = now() + timedelta(days=expires_days if expires_days else 7)
    token = secrets.token_urlsafe(24)
    s = ShareLink(
        token=token,
        document_id=doc_id,
        created_by=user.id,
        expires_at=expires,
        max_downloads=max_downloads,
    )
    db.add(s)
    db.commit()
    db.refresh(s)
    # Never persist the raw token in the audit log.
    audit(db, user, "SHARE_CREATE", "share", s.id, f"Document {doc_id} share={s.id}")
    return {
        "id": s.id,
        "token": s.token,
        "document_id": s.document_id,
        "created_by": s.created_by,
        "expires_at": s.expires_at,
        "max_downloads": s.max_downloads,
        "download_count": s.download_count,
        "created_at": s.created_at,
        "url": f"/api/shares/{s.token}",
    }


@router.get("/shares/{token}")
@limiter.limit(lambda: settings.share_rate_limit)
def use_share(
    token: str,
    request: Request,
    db: Session = Depends(get_db),
):
    s = db.query(ShareLink).filter(ShareLink.token == token).first()
    if not s:
        raise HTTPException(status_code=404, detail="Share link not found")
    if s.expires_at and s.expires_at < now():
        raise HTTPException(status_code=410, detail="Share link expired")
    d = db.get(Document, s.document_id)
    if not d:
        raise HTTPException(status_code=404, detail="Document not found")
    # Atomically claim one download; concurrent requests cannot exceed the cap.
    claimed = (
        db.query(ShareLink)
        .filter(
            ShareLink.id == s.id,
            or_(
                ShareLink.max_downloads.is_(None),
                ShareLink.download_count < ShareLink.max_downloads,
            ),
        )
        .update(
            {ShareLink.download_count: ShareLink.download_count + 1},
            synchronize_session=False,
        )
    )
    if not claimed:
        db.commit()
        raise HTTPException(status_code=410, detail="Download limit reached")
    db.commit()
    path = Path(d.file_path)
    if not path.exists():
        raise HTTPException(status_code=404, detail="File not found")
    audit(db, None, "SHARE_DOWNLOAD", "document", d.id, f"Share {s.id}")
    return FileResponse(path, filename=d.name, media_type=d.mime)


@router.get("/documents/{doc_id}/shares", response_model=list[ShareLinkOut])
def list_shares(
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
    is_privileged = user.role in ("superadmin", "admin")
    results = []
    for s in db.query(ShareLink).filter(ShareLink.document_id == doc_id).all():
        # Full tokens only for the creator/admins; others see a masked preview.
        owner = is_privileged or s.created_by == user.id
        token = s.token if owner else (s.token[:4] + "…" if s.token else "")
        results.append(
            {
                "id": s.id,
                "token": token,
                "document_id": s.document_id,
                "created_by": s.created_by,
                "expires_at": s.expires_at,
                "max_downloads": s.max_downloads,
                "download_count": s.download_count,
                "created_at": s.created_at,
                "url": f"/api/shares/{token}" if owner else None,
            }
        )
    return results


@router.delete("/documents/{doc_id}/shares/{share_id}")
def delete_share(
    doc_id: int,
    share_id: int,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    s = db.get(ShareLink, share_id)
    if not s or s.document_id != doc_id:
        raise HTTPException(status_code=404, detail="Share not found")
    if s.created_by != user.id and user.role not in ("superadmin", "admin"):
        raise HTTPException(status_code=403, detail="No permission")
    db.delete(s)
    db.commit()
    audit(db, user, "SHARE_DELETE", "share", share_id, f"Document {doc_id}")
    return {"ok": True}


# ---------------------------------------------------------------------------
# Retention policies
# ---------------------------------------------------------------------------
@router.get("/retention-policies", response_model=list[RetentionPolicyOut])
def list_policies(
    db: Session = Depends(get_db),
    user: User = Depends(require_role("superadmin", "admin")),
):
    return db.query(RetentionPolicy).order_by(RetentionPolicy.name).all()


@router.post("/retention-policies", response_model=RetentionPolicyOut)
def create_policy(
    payload: RetentionPolicyCreate,
    db: Session = Depends(get_db),
    user: User = Depends(require_role("superadmin", "admin")),
):
    p = RetentionPolicy(
        name=payload.name,
        folder_id=payload.folder_id,
        years=payload.years,
        action=payload.action,
        created_by=user.id,
    )
    db.add(p)
    db.commit()
    db.refresh(p)
    audit(db, user, "RETENTION_CREATE", "retention_policy", p.id, p.name)
    return p


@router.post("/retention-policies/apply")
def apply_policies(
    db: Session = Depends(get_db),
    user: User = Depends(require_role("superadmin", "admin")),
):
    affected = 0
    failed = 0
    for policy in db.query(RetentionPolicy).all():
        cutoff = now() - timedelta(days=policy.years * 365)
        q = db.query(Document).filter(Document.created_at < cutoff)
        if policy.folder_id:
            q = q.filter(Document.folder_id == policy.folder_id)
        for d in q.all():
            if policy.action == "archive":
                d.status = "archived"
                d.updated_at = now()
                affected += 1
            elif policy.action == "delete":
                # Purge dependent rows and the search-index entry FIRST, commit
                # the DB delete, and only then destroy files. A failure must
                # never leave the database pointing at deleted directories.
                try:
                    instance_ids = [
                        row[0]
                        for row in db.query(WorkflowInstance.id)
                        .filter(WorkflowInstance.document_id == d.id)
                        .all()
                    ]
                    if instance_ids:
                        db.query(Task).filter(Task.instance_id.in_(instance_ids)).delete(
                            synchronize_session=False
                        )
                        db.query(WorkflowInstance).filter(
                            WorkflowInstance.id.in_(instance_ids)
                        ).delete(synchronize_session=False)
                    db.query(Comment).filter(Comment.document_id == d.id).delete(
                        synchronize_session=False
                    )
                    db.query(ShareLink).filter(ShareLink.document_id == d.id).delete(
                        synchronize_session=False
                    )
                    db.query(DocumentVersion).filter(DocumentVersion.document_id == d.id).delete(
                        synchronize_session=False
                    )
                    db.query(CalendarEvent).filter(CalendarEvent.document_id == d.id).update(
                        {"document_id": None}, synchronize_session=False
                    )
                    remove_document(d.id)
                    db.delete(d)
                    db.commit()
                    ddir = doc_storage_dir(d.id)
                    if ddir.exists():
                        shutil.rmtree(ddir, ignore_errors=True)
                    affected += 1
                except Exception:
                    # One bad document must not abort the whole policy run.
                    db.rollback()
                    failed += 1
    audit(
        db, user, "RETENTION_APPLY", "retention_policy", None,
        f"Affected {affected} documents, {failed} failures",
    )
    return {"affected": affected, "failed": failed}


@router.delete("/retention-policies/{policy_id}")
def delete_policy(
    policy_id: int,
    db: Session = Depends(get_db),
    user: User = Depends(require_role("superadmin", "admin")),
):
    p = db.get(RetentionPolicy, policy_id)
    if not p:
        raise HTTPException(status_code=404, detail="Policy not found")
    db.delete(p)
    db.commit()
    audit(db, user, "RETENTION_DELETE", "retention_policy", policy_id, p.name)
    return {"ok": True}


# ---------------------------------------------------------------------------
# Reports / analytics
# ---------------------------------------------------------------------------
@router.get("/reports/summary", response_model=ReportSummary)
def summary_report(
    db: Session = Depends(get_db),
    user: User = Depends(require_role("superadmin", "admin")),
):
    users = db.query(User).count()
    groups = db.query(Group).count()
    folders = db.query(Folder).count()
    documents = db.query(Document).count()
    total_size = db.query(func.coalesce(func.sum(Document.size), 0)).scalar() or 0

    status_counts = {}
    for status, count in db.query(Document.status, func.count(Document.id)).group_by(Document.status).all():
        status_counts[status] = count

    top = (
        db.query(User.username, func.count(Document.id).label("cnt"))
        .join(Document, Document.created_by == User.id)
        .group_by(User.username)
        .order_by(func.count(Document.id).desc())
        .limit(10)
        .all()
    )
    recent_downloads = (
        db.query(AuditLog)
        .filter(AuditLog.action == "DOCUMENT_DOWNLOAD")
        .filter(AuditLog.timestamp > now() - timedelta(days=30))
        .count()
    )

    return {
        "users": users,
        "groups": groups,
        "folders": folders,
        "documents": documents,
        "total_size": total_size,
        "by_status": status_counts,
        "top_uploaders": [{"username": u, "documents": c} for u, c in top],
        "recent_downloads": recent_downloads,
    }
