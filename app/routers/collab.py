"""Collaboration and governance routes: templates, comments, shares, retention, reports."""
from __future__ import annotations

import hashlib
import json
import secrets
import shutil
from datetime import timedelta
from html import escape
from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException, Request, Response
from fastapi.responses import FileResponse, HTMLResponse
from pydantic import BaseModel
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
    CustomFieldValue,
    Document,
    DocumentAttachment,
    DocumentVersion,
    Folder,
    Group,
    MetadataTemplate,
    ProcessingJob,
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
from app.security import get_current_user, get_password_hash, require_role, verify_password
from app.storage import doc_storage_dir

router = APIRouter(prefix="/api", tags=["collaboration"])
# Unauthenticated routes for the public share pages (token acts as credential).
open_collab = APIRouter(tags=["collaboration-open"])

SHARE_KINDS = ("download", "view", "comment")

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
            "author_name": c.author_name,
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
        "author_name": c.author_name,
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
    password: str | None = None,
    name: str | None = None,
    kind: str = "download",
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    if kind not in SHARE_KINDS:
        raise HTTPException(status_code=400, detail=f"kind must be one of {SHARE_KINDS}")
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
        password_hash=get_password_hash(password) if password else None,
        name=name,
        kind=kind,
    )
    db.add(s)
    db.commit()
    db.refresh(s)
    # Never persist the raw token in the audit log.
    audit(db, user, "SHARE_CREATE", "share", s.id, f"Document {doc_id} share={s.id} kind={kind}")
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
        "name": s.name,
        "password_protected": bool(s.password_hash),
        "kind": s.kind,
    }


def _load_valid_share(db: Session, token: str, password: str | None) -> ShareLink:
    """Fetch a share and enforce expiry + password. 401 keeps the password
    challenge distinguishable from a dead link for the public page."""
    s = db.query(ShareLink).filter(ShareLink.token == token).first()
    if not s:
        raise HTTPException(status_code=404, detail="Share link not found")
    if s.expires_at and s.expires_at < now():
        raise HTTPException(status_code=410, detail="Share link expired")
    if s.password_hash:
        if not password or not verify_password(password, s.password_hash):
            raise HTTPException(status_code=401, detail="Password required")
    return s


@router.options("/shares/{token}")
def options_share(token: str, request: Request):
    """OPTIONS method for Microsoft Office desktop protocol and WebDAV discovery."""
    return Response(
        headers={
            "Allow": "OPTIONS, GET, HEAD, PUT, POST, PROPFIND, LOCK, UNLOCK",
            "DAV": "1, 2",
            "MS-Author-Via": "DAV",
            "Accept-Ranges": "bytes",
        }
    )


@router.head("/shares/{token}")
def head_share(token: str, request: Request, db: Session = Depends(get_db)):
    """HEAD method for Office protocol handshake."""
    s = _load_valid_share(db, token)
    d = db.get(Document, s.document_id)
    if not d:
        raise HTTPException(status_code=404, detail="Document not found")
    path = Path(d.file_path) if d.file_path else None
    size = path.stat().st_size if path and path.exists() else (d.size or 0)
    return Response(
        headers={
            "Content-Type": d.mime or "application/octet-stream",
            "Content-Length": str(size),
            "Content-Disposition": f'inline; filename="{d.name}"',
            "MS-Author-Via": "DAV",
            "Accept-Ranges": "bytes",
            "DAV": "1, 2",
        }
    )


@router.api_route("/shares/{token}", methods=["PROPFIND", "LOCK", "UNLOCK"])
async def dav_share_control(token: str, request: Request, db: Session = Depends(get_db)):
    """Handle WebDAV metadata and lock control requests from Microsoft Office."""
    s = _load_valid_share(db, token)
    d = db.get(Document, s.document_id)
    if not d:
        raise HTTPException(status_code=404, detail="Document not found")
    
    method = request.method.upper()
    if method == "LOCK":
        lock_token = f"opaquelocktoken:{token}"
        xml_res = f"""<?xml version="1.0" encoding="utf-8" ?>
<D:prop xmlns:D="DAV:">
  <D:lockdiscovery>
    <D:activelock>
      <D:locktype><D:write/></D:locktype>
      <D:lockscope><D:exclusive/></D:lockscope>
      <D:depth>0</D:depth>
      <D:owner><D:href>urn:newtonedms:office</D:href></D:owner>
      <D:timeout>Second-3600</D:timeout>
      <D:locktoken><D:href>{lock_token}</D:href></D:locktoken>
      <D:lockroot><D:href>/api/shares/{token}</D:href></D:lockroot>
    </D:activelock>
  </D:lockdiscovery>
</D:prop>"""
        return Response(content=xml_res, media_type="application/xml; charset=utf-8", headers={"Lock-Token": f"<{lock_token}>"})
    elif method == "UNLOCK":
        return Response(status_code=204)
    else:  # PROPFIND
        path = Path(d.file_path) if d.file_path else None
        size = path.stat().st_size if path and path.exists() else (d.size or 0)
        xml_res = f"""<?xml version="1.0" encoding="utf-8" ?>
<D:multistatus xmlns:D="DAV:">
  <D:response>
    <D:href>/api/shares/{token}</D:href>
    <D:propstat>
      <D:prop>
        <D:displayname>{escape(d.name)}</D:displayname>
        <D:getcontentlength>{size}</D:getcontentlength>
        <D:getcontenttype>{d.mime or 'application/octet-stream'}</D:getcontenttype>
        <D:resourcetype/>
      </D:prop>
      <D:status>HTTP/1.1 200 OK</D:status>
    </D:propstat>
  </D:response>
</D:multistatus>"""
        return Response(content=xml_res, status_code=207, media_type="application/xml; charset=utf-8")


@router.put("/shares/{token}")
async def put_share(
    token: str,
    request: Request,
    db: Session = Depends(get_db),
):
    """PUT method allowing Microsoft Office to save edited documents directly back into the repository."""
    s = _load_valid_share(db, token)
    if s.kind not in ("edit", "all"):
        raise HTTPException(status_code=403, detail="Share link does not permit editing")
    d = db.get(Document, s.document_id)
    if not d or not d.file_path:
        raise HTTPException(status_code=404, detail="Document not found")
    
    path = Path(d.file_path)
    body_data = await request.body()
    if not body_data:
        raise HTTPException(status_code=400, detail="No content provided")
    
    # Save previous version
    prev_ver_num = d.current_version or 1
    target_dir = path.parent
    ver_dest = target_dir / f"version_{prev_ver_num}{path.suffix}"
    if path.exists() and not ver_dest.exists():
        shutil.copy2(path, ver_dest)
        db.add(DocumentVersion(
            document_id=d.id,
            version_number=prev_ver_num,
            file_path=str(ver_dest),
            size=path.stat().st_size,
            created_by=s.created_by,
            notes="Auto-archived before Office desktop edit",
        ))
    
    path.write_bytes(body_data)
    d.size = len(body_data)
    d.content_hash = hashlib.sha256(body_data).hexdigest()
    d.current_version = prev_ver_num + 1
    d.updated_at = now()
    db.commit()
    audit(db, s.created_by, "OFFICE_SAVE", "document", d.id, f"Direct desktop Office save via share token {s.token[:8]}")
    return {"status": "ok", "version": d.current_version, "size": d.size}


@router.get("/shares/{token}")
@limiter.limit(lambda: settings.share_rate_limit)
def use_share(
    token: str,
    request: Request,
    password: str | None = None,
    db: Session = Depends(get_db),
):
    s = _load_valid_share(db, token, password)
    d = db.get(Document, s.document_id)
    if not d:
        raise HTTPException(status_code=404, detail="Document not found")
    path = Path(d.file_path)
    if not path.exists():
        raise HTTPException(status_code=404, detail="File not found")
    
    response_headers = {
        "MS-Author-Via": "DAV",
        "Accept-Ranges": "bytes",
    }
    
    if s.kind in ("view", "comment"):
        audit(db, None, "SHARE_VIEW", "document", d.id, f"Share {s.id}")
        return FileResponse(
            path,
            filename=d.name,
            media_type=d.mime,
            content_disposition_type="inline",
            headers=response_headers,
        )
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
    audit(db, None, "SHARE_DOWNLOAD", "document", d.id, f"Share {s.id}")
    return FileResponse(path, filename=d.name, media_type=d.mime, headers=response_headers)


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
                "name": s.name,
                "password_protected": bool(s.password_hash),
                "kind": s.kind,
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
# Public share access (view-only / view+comment links render a page, the
# token in the URL is the credential, optionally plus a password)
# ---------------------------------------------------------------------------
class PublicCommentIn(BaseModel):
    text: str
    author: str | None = None
    password: str | None = None


@router.get("/shares/{token}/info")
def share_info(token: str, db: Session = Depends(get_db)):
    s = db.query(ShareLink).filter(ShareLink.token == token).first()
    if not s:
        raise HTTPException(status_code=404, detail="Share link not found")
    d = db.get(Document, s.document_id)
    if not d:
        raise HTTPException(status_code=404, detail="Document not found")
    return {
        "title": d.title or d.name,
        "mime": d.mime,
        "kind": s.kind or "download",
        "name": s.name,
        "requires_password": bool(s.password_hash),
        "expires_at": s.expires_at,
        "expired": bool(s.expires_at and s.expires_at < now()),
    }


@router.get("/shares/{token}/comments")
def share_comments(token: str, password: str | None = None, db: Session = Depends(get_db)):
    s = _load_valid_share(db, token, password)
    if s.kind != "comment":
        raise HTTPException(status_code=403, detail="This share does not allow comments")
    rows = (
        db.query(Comment)
        .filter(Comment.document_id == s.document_id)
        .order_by(Comment.created_at)
        .all()
    )
    return [
        {
            "author": c.author_name or "Anonymous",
            "text": c.text,
            "created_at": c.created_at,
        }
        for c in rows
    ]


@router.post("/shares/{token}/comments")
def share_add_comment(token: str, payload: PublicCommentIn, db: Session = Depends(get_db)):
    s = _load_valid_share(db, token, payload.password)
    if s.kind != "comment":
        raise HTTPException(status_code=403, detail="This share does not allow comments")
    text = (payload.text or "").strip()
    if not text or len(text) > 4000:
        raise HTTPException(status_code=400, detail="Comment text required (max 4000 chars)")
    author = (payload.author or "").strip()[:80] or "Anonymous"
    c = Comment(
        document_id=s.document_id,
        user_id=s.created_by,
        text=text,
        author_name=author,
    )
    db.add(c)
    db.commit()
    audit(db, None, "SHARE_COMMENT", "document", s.document_id, f"Share {s.id} by {author}")
    return {"ok": True}


def _share_password_gate(s: ShareLink, request: Request) -> str | None:
    """Return the verified password, or None when none is needed."""
    pw = request.query_params.get("password") or ""
    if s.password_hash and not verify_password(pw, s.password_hash):
        return None
    return pw


@open_collab.get("/share/{token}", response_class=HTMLResponse)
def document_share_page(token: str, request: Request, db: Session = Depends(get_db)):
    s = db.query(ShareLink).filter(ShareLink.token == token).first()
    if not s:
        raise HTTPException(status_code=404, detail="Share link not found")
    if s.expires_at and s.expires_at < now():
        return HTMLResponse("<!DOCTYPE html><html><body style='font-family:sans-serif;text-align:center;padding:4rem'><h2>This share link has expired.</h2></body></html>")
    d = db.get(Document, s.document_id)
    if not d:
        raise HTTPException(status_code=404, detail="Document not found")
    title = escape(d.title or d.name)
    pw = _share_password_gate(s, request)
    if pw is None:
        return HTMLResponse(
            f"""<!DOCTYPE html><html><head><meta charset="utf-8"/><title>{title}</title>
            <meta name="viewport" content="width=device-width,initial-scale=1"/>
            <style>body{{font-family:sans-serif;max-width:28rem;margin:4rem auto;padding:1rem}}
            input{{width:100%;padding:.5rem;margin:.4rem 0}}</style></head>
            <body><h2>{title}</h2><p>This share is password protected.</p>
            <form><input type="password" name="password" placeholder="Password" autofocus/>
            <button>Open</button></form></body></html>"""
        )
    kind = s.kind or "download"
    src = f"/api/shares/{escape(token)}" + (f"?password={escape(pw)}" if s.password_hash else "")
    file_url = (d.file_path or "").lower()
    if (d.mime or "").startswith("image/"):
        preview = f'<img src="{src}" alt="{title}" style="max-width:100%;border:1px solid #ddd"/>'
    elif (d.mime or "") == "application/pdf" or file_url.endswith(".pdf"):
        preview = f'<iframe src="{src}" title="{title}" style="width:100%;height:70vh;border:1px solid #ddd"></iframe>'
    elif (d.mime or "").startswith("text/"):
        preview = f'<iframe src="{src}" title="{title}" style="width:100%;height:50vh;border:1px solid #ddd"></iframe>'
    else:
        preview = "<p style='color:#666'>In-browser preview is not available for this file type.</p>"
    kind_label = {"view": "View only", "comment": "View &amp; comment", "download": "Download"}[kind] if kind in ("view", "comment", "download") else kind
    comment_box = ""
    if kind == "comment":
        pw_js = json.dumps(pw if s.password_hash else None)
        token_js = json.dumps(token)
        comment_box = f"""
        <h3>Comments</h3>
        <ul id="cmt-list" style="list-style:none;padding:0"></ul>
        <input id="cmt-author" placeholder="Your name" style="width:100%;padding:.5rem;margin:.4rem 0"/>
        <textarea id="cmt-text" placeholder="Write a comment…" rows="3" style="width:100%;padding:.5rem"></textarea>
        <button onclick="postComment()" style="padding:.5rem 1rem">Post comment</button>
        <script>
        const PW = {pw_js};
        const TOKEN = {token_js};
        function esc(s) {{ return String(s || "").replace(/[&<>"]/g, c => ({{"&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;"}}[c])); }}
        async function loadComments() {{
          const r = await fetch("/api/shares/" + TOKEN + "/comments" + (PW ? "?password=" + encodeURIComponent(PW) : ""));
          if (!r.ok) return;
          const cs = await r.json();
          document.getElementById("cmt-list").innerHTML = cs.map(c =>
            "<li><b>" + esc(c.author) + "</b> <small>" + new Date(c.created_at).toLocaleString() + "</small><div>" + esc(c.text) + "</div></li>"
          ).join("") || '<li style="color:#999">No comments yet</li>';
        }}
        async function postComment() {{
          const text = document.getElementById("cmt-text").value.trim();
          const author = document.getElementById("cmt-author").value.trim();
          if (!text) return;
          const r = await fetch("/api/shares/" + TOKEN + "/comments", {{
            method: "POST",
            headers: {{"Content-Type": "application/json"}},
            body: JSON.stringify({{ text: text, author: author, password: PW }}),
          }});
          if (!r.ok) {{ alert("Could not post comment"); return; }}
          document.getElementById("cmt-text").value = "";
          loadComments();
        }}
        loadComments();
        </script>"""
    download_btn = f'<p><a href="{src}" style="display:inline-block;padding:.6rem 1.2rem;background:#2563eb;color:#fff;text-decoration:none;border-radius:4px">Download file</a></p>' if kind == "download" else "<p style='color:#999;font-size:.9rem'>This link is view-only; downloading is disabled.</p>"
    return HTMLResponse(
        f"""<!DOCTYPE html><html><head><meta charset="utf-8"/><title>{title}</title>
        <meta name="viewport" content="width=device-width,initial-scale=1"/>
        <style>body{{font-family:sans-serif;max-width:52rem;margin:1.5rem auto;padding:1rem}}
        .badge{{display:inline-block;background:#e0e7ff;color:#3730a3;border-radius:4px;padding:.15rem .5rem;font-size:.8rem;margin-left:.5rem}}
        li{{border-bottom:1px solid #eee;padding:.5rem 0}}</style></head>
        <body><h2>{title}<span class="badge">{kind_label}</span></h2>
        {preview}
        {download_btn}
        {comment_box}
        <p style="color:#aaa;font-size:.75rem;margin-top:2rem">Shared via NewtonEDMS</p>
        </body></html>"""
    )


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
    from app.retention import apply_all

    result = apply_all(db)
    audit(
        db, user, "RETENTION_APPLY", "retention_policy", None,
        f"Affected {result['affected']} documents, {result['failed']} failures, {result['skipped_holds']} on hold",
    )
    return result


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
