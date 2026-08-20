"""Microsoft Office Integration API Router.

Exposes:
1. Desktop URI protocol launchers (ms-word, ms-excel, ms-powerpoint) & WebDAV direct edit.
2. WOPI session tokens & embedded Office Online co-authoring iframe viewer.
3. Office 365 Add-in XML & JSON manifests (Word, Excel, PowerPoint, Outlook).
4. OpenXML document properties inspection & synchronization.
5. Template placeholder merging for .docx and .xlsx files.
6. Excel (.xlsx) and Word (.docx) export generators.
7. Outlook Add-in email & attachment archiver.
"""
from __future__ import annotations

import base64
import datetime
import hashlib
import json
import logging
import secrets
from pathlib import Path
from typing import Any, List, Optional

from fastapi import APIRouter, Depends, HTTPException, Query, Request, Response
from fastapi.responses import HTMLResponse, JSONResponse, Response
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from app.branding import PRODUCT_NAME, PRODUCT_VERSION
from app.config import settings
from app.database import get_db
from app.models import Document, DocumentVersion, Folder, ShareLink, User
from app.permissions import has_permission
from app.security import get_current_user, get_optional_user, require_role
from app.storage import doc_storage_dir
from app.wopi import generate_wopi_token
from app.office_meta import (
    export_documents_to_excel,
    export_documents_to_word,
    get_office_properties,
    merge_excel_template,
    merge_word_template,
    update_office_properties,
)

logger = logging.getLogger("newtonedms.office")
router = APIRouter(prefix="/api/office", tags=["office"])


# Schemas
class PropertiesUpdate(BaseModel):
    title: Optional[str] = None
    author: Optional[str] = None
    subject: Optional[str] = None
    keywords: Optional[str] = None
    comments: Optional[str] = None
    category: Optional[str] = None
    custom: Optional[dict[str, Any]] = None


class TemplateMergeIn(BaseModel):
    target_name: Optional[str] = None
    target_folder_id: Optional[int] = None
    context: dict[str, Any] = Field(default_factory=dict)
    save_to_repository: bool = True


class ExportIn(BaseModel):
    document_ids: Optional[list[int]] = None
    folder_id: Optional[int] = None
    query: Optional[str] = None
    title: Optional[str] = "NewtonEDMS Export"


class OutlookArchiveIn(BaseModel):
    folder_id: Optional[int] = None
    subject: str
    from_address: str
    from_name: Optional[str] = None
    to_addresses: Optional[list[str]] = None
    sent_date: Optional[str] = None
    body_html: Optional[str] = None
    body_text: Optional[str] = None
    tags: Optional[list[str]] = None
    attachments: Optional[list[dict]] = None  # [{"filename": "...", "content_base64": "..."}]


# 1. Desktop Office URI Launcher
@router.get("/desktop-launch/{doc_id}")
def get_desktop_launch(
    doc_id: int,
    request: Request,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    """Generate Microsoft Office URI protocol handler links (ms-word:, ms-excel:, ms-powerpoint:)."""
    doc = db.get(Document, doc_id)
    if not doc or doc.deleted_at is not None:
        raise HTTPException(status_code=404, detail="Document not found")
    
    folder = db.get(Folder, doc.folder_id) if doc.folder_id else None
    if not has_permission(db, user, "read", folder, doc):
        raise HTTPException(status_code=403, detail="Read permission denied")
    
    can_write = has_permission(db, user, "write", folder, doc) and not bool(doc.locked_by or doc.checked_out_by)
    
    # Create secure token for direct WebDAV / Office access
    token = secrets.token_urlsafe(24)
    share = ShareLink(
        token=token,
        document_id=doc.id,
        created_by=user.id,
        kind="edit" if can_write else "download",
        name=f"office-desktop-{user.username}",
        max_downloads=50,
        expires_at=datetime.datetime.now(datetime.timezone.utc) + datetime.timedelta(hours=8),
    )
    db.add(share)
    db.commit()
    
    base_url = str(request.base_url).rstrip("/")
    ext = Path(doc.name or "").suffix.lower()
    
    proto = "ms-word"
    app_name = "Microsoft Word"
    if ext in (".xlsx", ".xls", ".xlsm", ".csv"):
        proto = "ms-excel"
        app_name = "Microsoft Excel"
    elif ext in (".pptx", ".ppt"):
        proto = "ms-powerpoint"
        app_name = "Microsoft PowerPoint"
    elif ext in (".vsdx", ".vsd"):
        proto = "ms-visio"
        app_name = "Microsoft Visio"
    elif ext in (".accdb", ".mdb"):
        proto = "ms-access"
        app_name = "Microsoft Access"
        
    action_prefix = "ofe" if can_write else "ofv"
    direct_url = f"{base_url}/api/shares/{token}"
    webdav_url = f"{base_url}/webdav/{doc.name}?token={token}"
    protocol_uri = f"{proto}:{action_prefix}|u|{direct_url}"
    
    return {
        "document_id": doc.id,
        "name": doc.name,
        "extension": ext,
        "app_name": app_name,
        "can_write": can_write,
        "protocol_uri": protocol_uri,
        "webdav_url": webdav_url,
        "direct_url": direct_url,
        "share_token": token,
    }


# 2. WOPI Session & Embedded Office Frame
@router.get("/wopi/session/{doc_id}")
def create_wopi_session(
    doc_id: int,
    request: Request,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    """Create a WOPI token and session metadata for iframe embedding."""
    doc = db.get(Document, doc_id)
    if not doc or doc.deleted_at is not None:
        raise HTTPException(status_code=404, detail="Document not found")
    
    folder = db.get(Folder, doc.folder_id) if doc.folder_id else None
    if not has_permission(db, user, "read", folder, doc):
        raise HTTPException(status_code=403, detail="Read permission denied")
    
    can_write = has_permission(db, user, "write", folder, doc) and not bool(doc.locked_by or doc.checked_out_by)
    token = generate_wopi_token(doc.id, user.id, user.username, can_write=can_write)
    
    base_url = str(request.base_url).rstrip("/")
    wopi_src = f"{base_url}/wopi/files/{doc.id}"
    
    # Check configured WOPI client (Collabora / OnlyOffice / Office Online Server / Microsoft 365)
    client_url = getattr(settings, "wopi_client_url", "") or getattr(settings, "office_online_url", "") or ""
    
    frame_url = f"{base_url}/api/office/wopi/frame/{doc.id}?mode={'edit' if can_write else 'view'}"
    
    return {
        "document_id": doc.id,
        "name": doc.name,
        "access_token": token,
        "access_token_ttl": getattr(settings, "wopi_token_ttl_minutes", 1440) * 60,
        "wopi_src": wopi_src,
        "frame_url": frame_url,
        "client_url": client_url,
        "can_write": can_write,
    }


@router.get("/wopi/frame/{doc_id}", response_class=HTMLResponse)
def render_wopi_frame(
    doc_id: int,
    request: Request,
    mode: str = Query("edit"),
    token: Optional[str] = Query(None),
    db: Session = Depends(get_db),
    user: Optional[User] = Depends(get_optional_user),
):
    """Render a full-screen, responsive Office Online / WOPI workspace viewer and editor."""
    doc = db.get(Document, doc_id)
    if not doc or doc.deleted_at is not None:
        raise HTTPException(status_code=404, detail="Document not found")
    
    # If no token passed, generate one for authenticated user
    if not token and user:
        folder = db.get(Folder, doc.folder_id) if doc.folder_id else None
        can_write = (mode == "edit") and has_permission(db, user, "write", folder, doc) and not bool(doc.locked_by or doc.checked_out_by)
        token = generate_wopi_token(doc.id, user.id, user.username, can_write=can_write)
    
    if not token:
        raise HTTPException(status_code=401, detail="Authentication token required")
    
    base_url = str(request.base_url).rstrip("/")
    wopi_src = f"{base_url}/wopi/files/{doc.id}"
    wopi_client = getattr(settings, "wopi_client_url", "") or getattr(settings, "office_online_url", "")
    
    ext = Path(doc.name or "").suffix.lower()
    icon_cls = "fa-file-word"
    if ext in (".xlsx", ".xls", ".csv"):
        icon_cls = "fa-file-excel"
    elif ext in (".pptx", ".ppt"):
        icon_cls = "fa-file-powerpoint"
    
    html = f"""<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="UTF-8">
  <meta name="viewport" content="width=device-width, initial-scale=1.0">
  <title>{doc.name} — NewtonEDMS Office</title>
  <link rel="icon" href="/static/favicon.svg" type="image/svg+xml">
  <link rel="stylesheet" href="/static/fontawesome/all.min.css">
  <style>
    * {{ box-sizing: border-box; margin: 0; padding: 0; }}
    body {{ font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, sans-serif; background: #0f172a; color: #f8fafc; height: 100vh; display: flex; flex-direction: column; overflow: hidden; }}
    header {{ height: 50px; background: #1e293b; border-bottom: 1px solid #334155; display: flex; align-items: center; justify-content: space-between; padding: 0 16px; }}
    .title-box {{ display: flex; align-items: center; gap: 12px; font-weight: 600; font-size: 15px; }}
    .title-box i {{ color: #38bdf8; font-size: 18px; }}
    .badge {{ font-size: 11px; padding: 3px 8px; border-radius: 999px; background: #0284c7; color: #fff; font-weight: 500; }}
    .btn {{ background: #334155; border: none; color: #f8fafc; padding: 7px 14px; border-radius: 6px; cursor: pointer; font-size: 13px; font-weight: 500; display: inline-flex; align-items: center; gap: 6px; text-decoration: none; transition: background 0.15s; }}
    .btn:hover {{ background: #475569; }}
    .btn.primary {{ background: #0284c7; }}
    .btn.primary:hover {{ background: #0369a1; }}
    #wopi-container {{ flex: 1; position: relative; background: #1e293b; }}
    iframe {{ width: 100%; height: 100%; border: none; }}
    .notice {{ position: absolute; inset: 0; display: flex; flex-direction: column; align-items: center; justify-content: center; text-align: center; padding: 24px; }}
    .notice-card {{ max-width: 540px; background: #1e293b; border: 1px solid #334155; border-radius: 12px; padding: 32px; box-shadow: 0 10px 25px -5px rgba(0,0,0,0.5); }}
    .notice-card h2 {{ font-size: 20px; margin-bottom: 12px; color: #f8fafc; }}
    .notice-card p {{ color: #94a3b8; font-size: 14px; line-height: 1.6; margin-bottom: 20px; }}
    .btn-row {{ display: flex; gap: 10px; justify-content: center; }}
  </style>
</head>
<body>
  <header>
    <div class="title-box">
      <a href="/" class="btn" title="Back to NewtonEDMS"><i class="fa-solid fa-arrow-left"></i> NewtonEDMS</a>
      <i class="fa-solid {icon_cls}"></i>
      <span>{doc.name}</span>
      <span class="badge">Version {doc.version or '1.0'}</span>
      <span class="badge" style="background:#059669"><i class="fa-solid fa-cloud"></i> Live WOPI Host</span>
    </div>
    <div style="display:flex;gap:8px">
      <a href="/api/documents/{doc.id}/download" class="btn"><i class="fa-solid fa-download"></i> Download</a>
    </div>
  </header>
  <div id="wopi-container">
    {'<iframe id="wopi-frame" name="wopi-frame" src="' + wopi_client + '?WOPISrc=' + wopi_src + '&access_token=' + token + '" allowfullscreen></iframe>' if wopi_client else f'''
    <div class="notice">
      <div class="notice-card">
        <i class="fa-solid fa-network-wired" style="font-size:40px;color:#38bdf8;margin-bottom:16px"></i>
        <h2>NewtonEDMS WOPI Protocol Ready</h2>
        <p>NewtonEDMS is serving standard WOPI endpoints for this document at:<br><code style="background:#0f172a;padding:4px 8px;border-radius:4px;color:#38bdf8;display:inline-block;margin-top:8px;font-size:12px">{wopi_src}</code></p>
        <p>You can connect your Office Online Server, Microsoft 365, Collabora, or OnlyOffice WOPI client by configuring <code>EDMS_WOPI_CLIENT_URL</code> in your settings.</p>
        <div class="btn-row">
          <a href="/api/documents/{doc.id}/download" class="btn primary"><i class="fa-solid fa-download"></i> Download Document</a>
          <button class="btn" onclick="openDesktop()"><i class="fa-solid fa-desktop"></i> Open in Desktop Office</button>
        </div>
      </div>
    </div>
    '''}
  </div>
  <script>
    async function openDesktop() {{
      const r = await fetch('/api/office/desktop-launch/{doc.id}');
      const data = await r.json();
      if (data.protocol_uri) {{
        window.location.href = data.protocol_uri;
      }}
    }}
  </script>
</body>
</html>"""
    return HTMLResponse(content=html)


# 3. Microsoft Office 365 Add-in (Manifests & Info)
@router.get("/addin/manifest.xml", response_class=Response)
def get_addin_manifest_xml(request: Request):
    """Generate a standard Microsoft Office Add-in XML Manifest for Word, Excel, PowerPoint, and Outlook."""
    base_url = str(request.base_url).rstrip("/")
    taskpane_url = f"{base_url}/static/office-addin/taskpane.html"
    icon_url = f"{base_url}/static/favicon.svg"
    
    xml_content = f"""<?xml version="1.0" encoding="UTF-8"?>
<OfficeApp 
          xmlns="http://schemas.microsoft.com/office/appforoffice/1.1" 
          xmlns:xsi="http://www.w3.org/2001/XMLSchema-instance" 
          xmlns:bt="http://schemas.microsoft.com/office/officeappbasictypes/1.0" 
          xmlns:ov="http://schemas.microsoft.com/office/taskpaneappversionoverrides" 
          xsi:type="TaskPaneApp">
  <Id>b7c84493-2475-4bb6-a94f-9e797a7a67cb</Id>
  <Version>{PRODUCT_VERSION}</Version>
  <ProviderName>NewtonEDMS</ProviderName>
  <DefaultLocale>en-US</DefaultLocale>
  <DisplayName DefaultValue="NewtonEDMS"/>
  <Description DefaultValue="Access, search, insert, and save documents directly between Microsoft Office (Word, Excel, PowerPoint, Outlook) and NewtonEDMS."/>
  <IconUrl DefaultValue="{icon_url}"/>
  <HighResolutionIconUrl DefaultValue="{icon_url}"/>
  <SupportUrl DefaultValue="{base_url}/#settings"/>
  <AppDomains>
    <AppDomain>{base_url}</AppDomain>
  </AppDomains>
  <Hosts>
    <Host Name="Document"/>
    <Host Name="Workbook"/>
    <Host Name="Presentation"/>
    <Host Name="Mailbox"/>
  </Hosts>
  <DefaultSettings>
    <SourceLocation DefaultValue="{taskpane_url}"/>
  </DefaultSettings>
  <Permissions>ReadWriteDocument</Permissions>
  <VersionOverrides xmlns="http://schemas.microsoft.com/office/taskpaneappversionoverrides" xsi:type="VersionOverridesV1_0">
    <Hosts>
      <Host xsi:type="Document">
        <DesktopFormFactor>
          <ExtensionPoint xsi:type="PrimaryCommandSurface">
            <CustomTab id="TabNewtonEDMS">
              <Group id="NewtonGroup">
                <Label resid="NewtonGroupLabel"/>
                <Icon>
                  <bt:Image size="16" resid="Icon16"/>
                  <bt:Image size="32" resid="Icon32"/>
                  <bt:Image size="80" resid="Icon80"/>
                </Icon>
                <Control xsi:type="Button" id="NewtonTaskpaneBtn">
                  <Label resid="NewtonButtonLabel"/>
                  <Supertip>
                    <Title resid="NewtonButtonTitle"/>
                    <Description resid="NewtonButtonDesc"/>
                  </Supertip>
                  <Icon>
                    <bt:Image size="16" resid="Icon16"/>
                    <bt:Image size="32" resid="Icon32"/>
                    <bt:Image size="80" resid="Icon80"/>
                  </Icon>
                  <Action xsi:type="ShowTaskpane">
                    <TaskpaneId>NewtonTaskpane</TaskpaneId>
                    <SourceLocation resid="TaskpaneUrl"/>
                  </Action>
                </Control>
              </Group>
              <Label resid="TabNewtonLabel"/>
            </CustomTab>
          </ExtensionPoint>
        </DesktopFormFactor>
      </Host>
      <Host xsi:type="Workbook">
        <DesktopFormFactor>
          <ExtensionPoint xsi:type="PrimaryCommandSurface">
            <CustomTab id="TabNewtonEDMSExcel">
              <Group id="NewtonGroupExcel">
                <Label resid="NewtonGroupLabel"/>
                <Icon>
                  <bt:Image size="16" resid="Icon16"/>
                  <bt:Image size="32" resid="Icon32"/>
                  <bt:Image size="80" resid="Icon80"/>
                </Icon>
                <Control xsi:type="Button" id="NewtonTaskpaneBtnExcel">
                  <Label resid="NewtonButtonLabel"/>
                  <Supertip>
                    <Title resid="NewtonButtonTitle"/>
                    <Description resid="NewtonButtonDesc"/>
                  </Supertip>
                  <Icon>
                    <bt:Image size="16" resid="Icon16"/>
                    <bt:Image size="32" resid="Icon32"/>
                    <bt:Image size="80" resid="Icon80"/>
                  </Icon>
                  <Action xsi:type="ShowTaskpane">
                    <TaskpaneId>NewtonTaskpaneExcel</TaskpaneId>
                    <SourceLocation resid="TaskpaneUrl"/>
                  </Action>
                </Control>
              </Group>
              <Label resid="TabNewtonLabel"/>
            </CustomTab>
          </ExtensionPoint>
        </DesktopFormFactor>
      </Host>
    </Hosts>
    <Resources>
      <bt:Images>
        <bt:Image id="Icon16" DefaultValue="{icon_url}"/>
        <bt:Image id="Icon32" DefaultValue="{icon_url}"/>
        <bt:Image id="Icon80" DefaultValue="{icon_url}"/>
      </bt:Images>
      <bt:Urls>
        <bt:Url id="TaskpaneUrl" DefaultValue="{taskpane_url}"/>
      </bt:Urls>
      <bt:ShortStrings>
        <bt:String id="TabNewtonLabel" DefaultValue="NewtonEDMS"/>
        <bt:String id="NewtonGroupLabel" DefaultValue="Repository"/>
        <bt:String id="NewtonButtonLabel" DefaultValue="NewtonEDMS"/>
        <bt:String id="NewtonButtonTitle" DefaultValue="Open NewtonEDMS"/>
      </bt:ShortStrings>
      <bt:LongStrings>
        <bt:String id="NewtonButtonDesc" DefaultValue="Open the NewtonEDMS document repository explorer, template manager, and archiver."/>
      </bt:LongStrings>
    </Resources>
  </VersionOverrides>
</OfficeApp>
"""
    return Response(
        content=xml_content,
        media_type="application/xml",
        headers={"Content-Disposition": 'attachment; filename="newtonedms-office-manifest.xml"'},
    )


@router.get("/addin/manifest.json")
def get_addin_manifest_json(request: Request):
    """Generate modern Microsoft 365 Unified JSON Manifest for Microsoft Office."""
    base_url = str(request.base_url).rstrip("/")
    return {
        "$schema": "https://developer.microsoft.com/json-schemas/teams/v1.16/MicrosoftTeams.schema.json",
        "manifestVersion": "1.16",
        "version": PRODUCT_VERSION,
        "id": "b7c84493-2475-4bb6-a94f-9e797a7a67cb",
        "packageName": "com.newtonedms.office",
        "developer": {
            "name": "NewtonEDMS",
            "websiteUrl": base_url,
            "privacyUrl": f"{base_url}/privacy",
            "termsOfUseUrl": f"{base_url}/terms",
        },
        "icons": {
            "color": f"{base_url}/static/favicon.svg",
            "outline": f"{base_url}/static/favicon.svg",
        },
        "name": {
            "short": "NewtonEDMS",
            "full": "NewtonEDMS Office Integration",
        },
        "description": {
            "short": "Document management & capture in Microsoft Office",
            "full": "Save documents, browse folders, insert metadata, and archive Outlook emails directly in NewtonEDMS.",
        },
        "accentColor": "#0284C7",
        "extensions": [
            {
                "requirements": {"capabilities": [{"name": "Office.js"}]},
                "runtimes": [
                    {
                        "id": "NewtonTaskpaneRuntime",
                        "type": "general",
                        "code": {"page": f"{base_url}/static/office-addin/taskpane.html"},
                        "lifetime": "short",
                    }
                ],
            }
        ],
    }


@router.get("/addin/info")
def get_addin_info(request: Request):
    """Returns Office Add-in information, sideload instructions, and URLs."""
    base_url = str(request.base_url).rstrip("/")
    return {
        "name": "NewtonEDMS Office Integration",
        "version": PRODUCT_VERSION,
        "manifest_xml_url": f"{base_url}/api/office/addin/manifest.xml",
        "manifest_json_url": f"{base_url}/api/office/addin/manifest.json",
        "taskpane_url": f"{base_url}/static/office-addin/taskpane.html",
        "supported_apps": ["Word", "Excel", "PowerPoint", "Outlook"],
        "features": [
            "Repository Explorer & Search",
            "Save Active Document directly to NewtonEDMS",
            "Insert Metadata, Custom Fields & Snippets",
            "Outlook 1-Click Email & Attachment Archiving",
            "Version Compare & Check-in / Check-out",
        ],
        "sideload_guide": "Download manifest.xml and sideload in Word/Excel via Insert > Add-ins > Shared Folder or Office 365 Admin Center.",
    }


# 4. OpenXML Document Properties (Read / Sync)
@router.get("/properties/{doc_id}")
def inspect_office_properties(
    doc_id: int,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    """Read core and custom metadata properties from Word, Excel, or PowerPoint files."""
    doc = db.get(Document, doc_id)
    if not doc or doc.deleted_at is not None:
        raise HTTPException(status_code=404, detail="Document not found")
    
    folder = db.get(Folder, doc.folder_id) if doc.folder_id else None
    if not has_permission(db, user, "read", folder, doc):
        raise HTTPException(status_code=403, detail="Read permission denied")
    
    if not doc.file_path:
        return {"properties": {}, "supported": False}
    
    file_path = Path(doc.file_path)
    props = get_office_properties(file_path)
    return {
        "document_id": doc.id,
        "name": doc.name,
        "supported": file_path.suffix.lower() in (".docx", ".xlsx", ".pptx", ".xlsm"),
        "properties": props,
    }


@router.post("/properties/{doc_id}")
def sync_office_properties(
    doc_id: int,
    payload: PropertiesUpdate,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    """Write/synchronize metadata properties into Word, Excel, or PowerPoint files."""
    doc = db.get(Document, doc_id)
    if not doc or doc.deleted_at is not None:
        raise HTTPException(status_code=404, detail="Document not found")
    
    folder = db.get(Folder, doc.folder_id) if doc.folder_id else None
    if not has_permission(db, user, "write", folder, doc) or bool(doc.locked_by or doc.checked_out_by):
        raise HTTPException(status_code=403, detail="Write permission denied")
    
    if not doc.file_path:
        raise HTTPException(status_code=400, detail="Document file path not found")
    
    file_path = Path(doc.file_path)
    props_dict = payload.model_dump(exclude_unset=True)
    
    ok = update_office_properties(file_path, props_dict)
    if not ok:
        raise HTTPException(status_code=400, detail="Failed to write Office properties (unsupported format or write error)")
    
    # Update document timestamp and hash
    doc.updated_at = datetime.datetime.now(datetime.timezone.utc)
    doc.content_hash = hashlib.sha256(file_path.read_bytes()).hexdigest()
    doc.size = file_path.stat().st_size
    db.commit()
    
    return {"status": "success", "updated_properties": props_dict}


# 5. Template Placeholder Merge Engine
@router.post("/templates/{doc_id}/merge")
def merge_office_template(
    doc_id: int,
    payload: TemplateMergeIn,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    """Merge placeholder values (e.g. {{title}}, {{custom_field}}, {{date}}) into a Word or Excel template."""
    doc = db.get(Document, doc_id)
    if not doc or doc.deleted_at is not None:
        raise HTTPException(status_code=404, detail="Template document not found")
    
    folder = db.get(Folder, doc.folder_id) if doc.folder_id else None
    if not has_permission(db, user, "read", folder, doc):
        raise HTTPException(status_code=403, detail="Read permission denied")
    
    if not doc.file_path or not Path(doc.file_path).exists():
        raise HTTPException(status_code=404, detail="Template file not found on disk")
    
    file_path = Path(doc.file_path)
    ext = file_path.suffix.lower()
    if ext not in (".docx", ".xlsx"):
        raise HTTPException(status_code=400, detail="Template merging requires a .docx or .xlsx template")
    
    # Assemble merge context
    context = dict(payload.context)
    context.setdefault("doc_id", doc.id)
    context.setdefault("template_name", doc.name)
    context.setdefault("author", getattr(user, "full_name", None) or user.username)
    context.setdefault("date", datetime.date.today().isoformat())
    context.setdefault("datetime", datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S"))
    
    target_folder_id = payload.target_folder_id or doc.folder_id
    target_name = payload.target_name or f"Generated_{Path(doc.name).stem}_{datetime.date.today().isoformat()}{ext}"
    
    # Create new document record in DB
    new_doc = Document(
        folder_id=target_folder_id,
        name=target_name,
        title=target_name,
        mime=doc.mime or "application/octet-stream",
        file_path="",
        created_by=user.id,
        current_version=1,
        notes=f"Generated from template #{doc.id} ({doc.name})",
    )
    db.add(new_doc)
    db.commit()
    db.refresh(new_doc)
    
    target_dir = doc_storage_dir(new_doc.id)
    target_dir.mkdir(parents=True, exist_ok=True)
    target_file = target_dir / f"content{ext}"
    
    if ext == ".docx":
        merge_word_template(file_path, target_file, context)
    else:
        merge_excel_template(file_path, target_file, context)
        
    new_doc.file_path = str(target_file)
    new_doc.size = target_file.stat().st_size
    new_doc.content_hash = hashlib.sha256(target_file.read_bytes()).hexdigest()
    db.commit()
    
    return {
        "status": "success",
        "new_document_id": new_doc.id,
        "name": new_doc.name,
        "folder_id": new_doc.folder_id,
        "download_url": f"/api/documents/{new_doc.id}/download",
    }


# 6. Professional Excel & Word Exporters
@router.post("/export/excel")
def export_excel(
    payload: ExportIn,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    """Export document listings to a styled Excel .xlsx spreadsheet."""
    q = db.query(Document).filter(Document.deleted_at.is_(None))
    if payload.document_ids:
        q = q.filter(Document.id.in_(payload.document_ids))
    elif payload.folder_id:
        q = q.filter(Document.folder_id == payload.folder_id)
        
    docs = q.order_by(Document.id.desc()).limit(500).all()
    
    doc_dicts = []
    for d in docs:
        f = db.get(Folder, d.folder_id) if d.folder_id else None
        if not has_permission(db, user, "read", f, d):
            continue
        doc_dicts.append({
            "id": d.id,
            "name": d.name,
            "folder_id": d.folder_id,
            "folder_name": f.name if f else "Root",
            "version": f"{d.current_version or 1}.0",
            "status": d.status or "draft",
            "size": d.size or 0,
            "tags": d.tags or "",
            "updated_at": d.updated_at or d.created_at,
        })
        
    content = export_documents_to_excel(doc_dicts, title=payload.title or "Documents Export")
    filename = f"NewtonEDMS_Export_{datetime.date.today().isoformat()}.xlsx"
    
    return Response(
        content=content,
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


@router.post("/export/word")
def export_word(
    payload: ExportIn,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    """Export document summary dossier to a formatted Word .docx document."""
    q = db.query(Document).filter(Document.deleted_at.is_(None))
    if payload.document_ids:
        q = q.filter(Document.id.in_(payload.document_ids))
    elif payload.folder_id:
        q = q.filter(Document.folder_id == payload.folder_id)
        
    docs = q.order_by(Document.id.desc()).limit(100).all()
    
    doc_dicts = []
    for d in docs:
        f = db.get(Folder, d.folder_id) if d.folder_id else None
        if not has_permission(db, user, "read", f, d):
            continue
        doc_dicts.append({
            "id": d.id,
            "name": d.name,
            "folder_id": d.folder_id,
            "folder_name": f.name if f else "Root",
            "version": f"{d.current_version or 1}.0",
            "status": d.status or "draft",
            "size": d.size or 0,
            "tags": d.tags or "",
            "notes": d.notes or "",
        })
        
    content = export_documents_to_word(doc_dicts, title=payload.title or "Document Dossier")
    filename = f"NewtonEDMS_Dossier_{datetime.date.today().isoformat()}.docx"
    
    return Response(
        content=content,
        media_type="application/vnd.openxmlformats-officedocument.wordprocessingml.document",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


# 7. Outlook Add-in Email & Attachment Ingestion
@router.post("/outlook/archive")
def archive_outlook_mail(
    payload: OutlookArchiveIn,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    """Archive email message and attachments directly from Outlook Office Add-in into NewtonEDMS."""
    folder_id = payload.folder_id
    if not folder_id:
        root = db.query(Folder).filter(Folder.parent_id.is_(None)).first()
        folder_id = root.id if root else None
        
    folder = db.get(Folder, folder_id) if folder_id else None
    if folder and not has_permission(db, user, "write", folder):
        raise HTTPException(status_code=403, detail="Write permission denied for target folder")
    
    # 1. Create main email record
    email_filename = f"Email - {payload.subject[:60].replace('/', '_').replace(chr(92), '_')}.html"
    tags_str = ", ".join(payload.tags) if isinstance(payload.tags, list) else (payload.tags or "email, outlook")
    
    email_doc = Document(
        folder_id=folder_id,
        name=email_filename,
        title=payload.subject,
        mime="text/html",
        file_path="",
        created_by=user.id,
        current_version=1,
        notes=f"Archived from Microsoft Outlook by {user.username}.\nFrom: {payload.from_name or ''} <{payload.from_address}>\nSent: {payload.sent_date or ''}",
        tags=tags_str,
        source="outlook",
    )
    db.add(email_doc)
    db.commit()
    db.refresh(email_doc)
    
    email_body = payload.body_html or f"<pre>{payload.body_text or ''}</pre>"
    full_html = f"""<!DOCTYPE html>
<html>
<head><meta charset="utf-8"><title>{payload.subject}</title>
<style>body{{font-family:Segoe UI,sans-serif;padding:24px;color:#1e293b;}} .meta{{background:#f1f5f9;padding:12px;border-radius:6px;margin-bottom:20px;font-size:13px;line-height:1.6;}}</style>
</head>
<body>
<div class="meta">
  <strong>Subject:</strong> {payload.subject}<br>
  <strong>From:</strong> {payload.from_name or ''} &lt;{payload.from_address}&gt;<br>
  <strong>Date:</strong> {payload.sent_date or datetime.datetime.now().isoformat()}<br>
  <strong>To:</strong> {', '.join(payload.to_addresses or [])}
</div>
<div class="content">{email_body}</div>
</body>
</html>"""
    
    dest_dir = doc_storage_dir(email_doc.id)
    dest_dir.mkdir(parents=True, exist_ok=True)
    target_file = dest_dir / "content.html"
    target_file.write_text(full_html, encoding="utf-8")
    
    email_doc.file_path = str(target_file)
    email_doc.size = len(full_html.encode("utf-8"))
    email_doc.content_hash = hashlib.sha256(full_html.encode("utf-8")).hexdigest()
    db.commit()
    
    saved_attachments = []
    # 2. Archive any attachments
    if payload.attachments:
        for att in payload.attachments:
            name = att.get("filename") or "Attachment"
            b64_data = att.get("content_base64") or ""
            if not b64_data:
                continue
            try:
                raw_bytes = base64.b64decode(b64_data)
            except Exception:
                continue
                
            att_doc = Document(
                folder_id=folder_id,
                name=name,
                title=name,
                mime="application/octet-stream",
                file_path="",
                created_by=user.id,
                current_version=1,
                notes=f"Attachment from email '{payload.subject}'",
                tags="attachment, outlook",
                source="outlook",
            )
            db.add(att_doc)
            db.commit()
            db.refresh(att_doc)
            
            att_dir = doc_storage_dir(att_doc.id)
            att_dir.mkdir(parents=True, exist_ok=True)
            att_file = att_dir / f"content{Path(name).suffix}"
            att_file.write_bytes(raw_bytes)
            
            att_doc.file_path = str(att_file)
            att_doc.size = len(raw_bytes)
            att_doc.content_hash = hashlib.sha256(raw_bytes).hexdigest()
            db.commit()
            saved_attachments.append({"id": att_doc.id, "name": att_doc.name})
            
    return {
        "status": "success",
        "email_document_id": email_doc.id,
        "name": email_doc.name,
        "attachments_count": len(saved_attachments),
        "attachments": saved_attachments,
    }
