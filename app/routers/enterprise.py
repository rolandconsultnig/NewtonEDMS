"""Enterprise content-infrastructure APIs: automation, compliance, AI, connectors."""
from __future__ import annotations

import csv
import io
import json
import secrets
import shutil
import zipfile
from pathlib import Path

from fastapi import APIRouter, Depends, File, Form, HTTPException, Query, Request, UploadFile
from fastapi.responses import HTMLResponse, RedirectResponse, Response
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy.orm import Session

from app.audit import audit
from app.config import settings
from app.database import get_db, now
from app.models import (
    ArchiveLinkEntry,
    AutomationRule,
    BpmnDefinition,
    CaptureForm,
    Case,
    CaseDocument,
    CollabOp,
    ConnectorAccount,
    Document,
    Folder,
    FormSubmission,
    LegalHold,
    LegalHoldItem,
    ReadingConfirmation,
    RedactionRule,
    ReportDefinition,
    SystemSetting,
    User,
    ZoneTemplate,
)
from app.permissions import has_permission
from app.security import create_access_token, get_current_user, require_role
from app.storage import doc_storage_dir, save_upload

router = APIRouter(prefix="/api", tags=["enterprise"])
open_ent = APIRouter(tags=["enterprise-open"])


def _pdf_path(d: Document) -> Path:
    p = Path(d.pdf_file_path or d.file_path)
    if not p.exists():
        from app.backends import resolve

        p = resolve(d.file_path)
    return p


def _writable(db: Session, user: User, d: Document) -> Folder:
    if not d:
        raise HTTPException(404, "Document not found")
    f = db.get(Folder, d.folder_id)
    if not f:
        raise HTTPException(404, "Document not found")
    if not has_permission(db, user, "write", f, d):
        raise HTTPException(403, "No permission")
    from app.compliance import is_held

    if is_held(db, d) and user.role not in ("superadmin", "admin"):
        raise HTTPException(423, "Document is on legal hold")
    return f


# ----- Automation rules -----
class RuleIn(BaseModel):
    name: str
    event: str = "document_created"
    condition: dict | None = None
    actions: list | None = None
    enabled: bool = True


@router.get("/automation-rules")
def list_rules(db: Session = Depends(get_db), user: User = Depends(require_role("superadmin", "admin", "manager"))):
    return db.query(AutomationRule).order_by(AutomationRule.name).all()


@router.post("/automation-rules")
def create_rule(payload: RuleIn, db: Session = Depends(get_db), user: User = Depends(require_role("superadmin", "admin", "manager"))):
    row = AutomationRule(
        name=payload.name,
        event=payload.event,
        condition=payload.condition or {},
        actions=payload.actions or [],
        enabled=payload.enabled,
        created_by=user.id,
    )
    db.add(row)
    db.commit()
    db.refresh(row)
    audit(db, user, "RULE_CREATE", "automation_rule", row.id, row.name)
    return row


@router.delete("/automation-rules/{rule_id}")
def delete_rule(rule_id: int, db: Session = Depends(get_db), user: User = Depends(require_role("superadmin", "admin"))):
    row = db.get(AutomationRule, rule_id)
    if not row:
        raise HTTPException(404, "Not found")
    db.delete(row)
    db.commit()
    return {"ok": True}


# ----- Forms & barcodes -----
class FormIn(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    name: str
    folder_id: int
    form_schema: dict | None = Field(default=None, alias="schema")


@router.get("/forms")
def list_forms(db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    return db.query(CaptureForm).order_by(CaptureForm.name).all()


@router.post("/forms")
def create_form(payload: FormIn, db: Session = Depends(get_db), user: User = Depends(require_role("superadmin", "admin", "manager"))):
    if not db.get(Folder, payload.folder_id):
        raise HTTPException(404, "Folder not found")
    row = CaptureForm(
        name=payload.name,
        token=secrets.token_urlsafe(16),
        schema_json=payload.form_schema or {"fields": []},
        folder_id=payload.folder_id,
        created_by=user.id,
    )
    db.add(row)
    db.commit()
    db.refresh(row)
    return {"id": row.id, "token": row.token, "name": row.name, "url": f"/forms/{row.token}"}


@open_ent.get("/forms/{token}", response_class=HTMLResponse)
def render_capture_form(token: str, db: Session = Depends(get_db)):
    from app.forms_engine import render_form

    row = db.query(CaptureForm).filter(CaptureForm.token == token, CaptureForm.enabled.is_(True)).first()
    if not row:
        raise HTTPException(404, "Form not found")
    return HTMLResponse(render_form(row.schema_json or {}, f"/forms/{token}", row.name))


@open_ent.post("/forms/{token}")
async def submit_capture_form(token: str, request: Request, db: Session = Depends(get_db)):
    row = db.query(CaptureForm).filter(CaptureForm.token == token, CaptureForm.enabled.is_(True)).first()
    if not row:
        raise HTTPException(404, "Form not found")
    form = await request.form()
    payload = {k: str(v) for k, v in form.items() if k != "file"}
    upload = form.get("file")
    folder = db.get(Folder, row.folder_id)
    owner = db.get(User, row.created_by)
    doc = None
    if upload is not None and getattr(upload, "filename", None):
        from app.routers.documents import _upload_one

        doc = _upload_one(db, owner, folder, upload, title=payload.get("title") or upload.filename, metadata=payload)
    else:
        dest = doc_storage_dir(0)
        # metadata-only capture becomes a JSON document
        from app.models import DocumentVersion

        d = Document(
            name=f"form-{token[:8]}.json",
            title=payload.get("title") or row.name,
            folder_id=row.folder_id,
            tags="form",
            metadata_json=payload,
            created_by=row.created_by,
            size=len(json.dumps(payload)),
            mime="application/json",
            file_path="",
            source="form",
        )
        db.add(d)
        db.flush()
        path = doc_storage_dir(d.id) / "v1.json"
        path.write_text(json.dumps(payload, indent=2), encoding="utf-8")
        d.file_path = str(path)
        d.size = path.stat().st_size
        db.add(DocumentVersion(document_id=d.id, version_number=1, file_path=str(path), size=d.size, created_by=row.created_by, comment="Form capture"))
        db.commit()
        doc = d
    db.add(FormSubmission(form_id=row.id, document_id=doc.id if doc else None, payload=payload))
    db.commit()
    return HTMLResponse("<p>Submitted. You may close this window.</p>")


@router.get("/barcodes/code128")
def barcode_png(data: str = Query(...), user: User = Depends(get_current_user)):
    from app.forms_engine import code128_png

    return Response(code128_png(data), media_type="image/png")


# ----- Zones / IDP -----
class ZoneIn(BaseModel):
    name: str
    zones: list


@router.get("/zones")
def list_zones(db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    return db.query(ZoneTemplate).order_by(ZoneTemplate.name).all()


@router.post("/zones")
def create_zone(payload: ZoneIn, db: Session = Depends(get_db), user: User = Depends(require_role("superadmin", "admin", "manager"))):
    row = ZoneTemplate(name=payload.name, zones=payload.zones, created_by=user.id)
    db.add(row)
    db.commit()
    db.refresh(row)
    return row


@router.post("/documents/{doc_id}/idp")
def run_idp(doc_id: int, zone_id: int | None = None, db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    from app.idp import apply_zones, auto_capture

    d = db.get(Document, doc_id)
    if not d:
        raise HTTPException(404, "Not found")
    _writable(db, user, d)
    try:
        pdf = _pdf_path(d)
    except Exception:
        pdf = Path(d.file_path) if d.file_path else None
    captured = auto_capture(db, d, pdf)
    if zone_id:
        zt = db.get(ZoneTemplate, zone_id)
        if zt:
            captured.update(apply_zones(db, d, zt.zones or [], pdf))
    return {"captured": captured}


@router.post("/idp/train")
def train_idp(db: Session = Depends(get_db), user: User = Depends(require_role("superadmin", "admin"))):
    from app.idp import train

    return train(db)


# ----- Legal hold -----
class HoldIn(BaseModel):
    name: str
    reason: str = ""
    document_ids: list[int]
    until: str | None = None


@router.get("/legal-holds")
def list_holds(db: Session = Depends(get_db), user: User = Depends(require_role("superadmin", "admin"))):
    rows = db.query(LegalHold).order_by(LegalHold.created_at.desc()).all()
    out = []
    for h in rows:
        items = db.query(LegalHoldItem).filter(LegalHoldItem.hold_id == h.id).all()
        docs = []
        for it in items:
            d = db.get(Document, it.document_id)
            docs.append({"id": it.document_id, "title": (d.title or d.name) if d else f"#{it.document_id}"})
        out.append({
            "id": h.id,
            "name": h.name,
            "reason": h.reason,
            "active": h.active,
            "created_at": h.created_at,
            "documents": docs,
        })
    return out


@router.post("/legal-holds")
def create_hold(payload: HoldIn, db: Session = Depends(get_db), user: User = Depends(require_role("superadmin", "admin"))):
    from app.compliance import place_hold

    hold = place_hold(db, name=payload.name, reason=payload.reason, user=user, document_ids=payload.document_ids)
    audit(db, user, "LEGAL_HOLD", "legal_hold", hold.id, payload.name)
    return {"id": hold.id, "name": hold.name, "active": hold.active}


@router.post("/legal-holds/{hold_id}/release")
def release(hold_id: int, db: Session = Depends(get_db), user: User = Depends(require_role("superadmin", "admin"))):
    from app.compliance import release_hold

    hold = db.get(LegalHold, hold_id)
    if not hold:
        raise HTTPException(404, "Not found")
    release_hold(db, hold)
    audit(db, user, "LEGAL_HOLD_RELEASE", "legal_hold", hold_id, hold.name)
    return {"ok": True}


# ----- Redaction -----
class RedactIn(BaseModel):
    patterns: list[str] | None = None
    boxes: list[dict] | None = None
    rule_id: int | None = None


@router.get("/redaction-rules")
def list_redact(db: Session = Depends(get_db), user: User = Depends(require_role("superadmin", "admin", "manager"))):
    return db.query(RedactionRule).all()


@router.post("/redaction-rules")
async def create_redact_rule(request: Request, db: Session = Depends(get_db), user: User = Depends(require_role("superadmin", "admin"))):
    ctype = (request.headers.get("content-type") or "").lower()
    if "json" in ctype:
        payload = await request.json()
        name = payload.get("name") or "rule"
        patterns = payload.get("patterns") or []
    else:
        form = await request.form()
        name = form.get("name") or "rule"
        raw = form.get("patterns") or "[]"
        patterns = json.loads(raw) if isinstance(raw, str) else (raw or [])
    row = RedactionRule(name=name, patterns=list(patterns), created_by=user.id)
    db.add(row)
    db.commit()
    db.refresh(row)
    return row


@router.post("/documents/{doc_id}/redact")
def redact_doc(doc_id: int, payload: RedactIn, db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    from app.pdfops import redact, redact_text_patterns

    d = db.get(Document, doc_id)
    _writable(db, user, d)
    src = _pdf_path(d)
    dest = doc_storage_dir(d.id) / "redacted.pdf"
    patterns = list(payload.patterns or [])
    if payload.rule_id:
        rule = db.get(RedactionRule, payload.rule_id)
        if rule:
            patterns.extend(rule.patterns or [])
    if payload.boxes:
        redact(src, dest, payload.boxes)
        cleaned = d.extracted_text or ""
    else:
        dest, cleaned = redact_text_patterns(src, dest, patterns, d.extracted_text or "")
    d.pdf_file_path = str(dest)
    d.extracted_text = cleaned
    d.immutable = True
    db.commit()
    audit(db, user, "REDACT", "document", d.id, ",".join(patterns)[:200])
    return {"ok": True, "path": str(dest)}


# ----- PDF ops -----
class WatermarkIn(BaseModel):
    text: str
    position: str = "center"


@router.post("/documents/{doc_id}/watermark")
def watermark_doc(doc_id: int, payload: WatermarkIn, db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    from app.pdfops import watermark

    d = db.get(Document, doc_id)
    _writable(db, user, d)
    dest = doc_storage_dir(d.id) / "watermarked.pdf"
    watermark(_pdf_path(d), dest, payload.text, position=payload.position)
    d.pdf_file_path = str(dest)
    db.commit()
    return {"ok": True}


@router.post("/documents/{doc_id}/stamp")
def stamp_doc(doc_id: int, text: str = Form(...), db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    from app.pdfops import stamp

    d = db.get(Document, doc_id)
    _writable(db, user, d)
    dest = doc_storage_dir(d.id) / "stamped.pdf"
    stamp(_pdf_path(d), dest, text)
    d.pdf_file_path = str(dest)
    db.commit()
    return {"ok": True}


@router.post("/documents/{doc_id}/sign")
def sign_doc(doc_id: int, reason: str = Form("approved"), db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    from app.pdfops import sign_pdf

    d = db.get(Document, doc_id)
    _writable(db, user, d)
    dest = doc_storage_dir(d.id) / "signed.pdf"
    record = sign_pdf(_pdf_path(d), dest, signer=user.username, secret=settings.secret_key, reason=reason)
    d.pdf_file_path = str(dest)
    d.signed = True
    meta = dict(d.metadata_json or {})
    meta["signature"] = record
    d.metadata_json = meta
    db.commit()
    return record


@router.get("/documents/{doc_id}/sign/verify")
def verify_doc_signature(doc_id: int, db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    from app.pdfops import has_embedded_signature, verify_signature

    d = db.get(Document, doc_id)
    if not d:
        raise HTTPException(404, "Not found")
    f = db.get(Folder, d.folder_id)
    if not has_permission(db, user, "read", f, d):
        raise HTTPException(403)
    path = Path(d.pdf_file_path or d.file_path or "")
    if not path.exists():
        raise HTTPException(404, "No file")
    rec = ((d.metadata_json or {}).get("signature")) or {}
    embedded = has_embedded_signature(path)
    ok = verify_signature(path, rec, settings.secret_key) if rec else embedded
    return {"ok": bool(ok), "embedded": embedded, "method": rec.get("method"), "signer": rec.get("signer")}


@router.post("/documents/{doc_id}/split")
def split_pdf_pages(doc_id: int, db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    from app.pdfops import split_pdf

    d = db.get(Document, doc_id)
    _writable(db, user, d)
    pages = split_pdf(_pdf_path(d), doc_storage_dir(d.id) / "pages")
    return {"pages": [str(p) for p in pages], "count": len(pages)}


class MergeIn(BaseModel):
    document_ids: list[int]
    title: str = "merged.pdf"
    folder_id: int | None = None


@router.post("/pdf/merge")
def merge_docs(payload: MergeIn, db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    from app.convert import merge_pdfs

    paths = []
    folder_id = payload.folder_id
    for did in payload.document_ids:
        d = db.get(Document, did)
        if not d:
            continue
        f = db.get(Folder, d.folder_id)
        if not has_permission(db, user, "read", f, d):
            raise HTTPException(403, "No permission")
        folder_id = folder_id or d.folder_id
        paths.append(_pdf_path(d))
    if len(paths) < 2:
        raise HTTPException(400, "Need at least two PDFs")
    dest_dir = doc_storage_dir(0)
    tmp = dest_dir / f"merge_{secrets.token_hex(4)}.pdf"
    merge_pdfs(paths, tmp)
    from starlette.datastructures import UploadFile as StarUpload

    folder = db.get(Folder, folder_id)
    data = tmp.read_bytes()
    up = StarUpload(filename=payload.title if payload.title.endswith(".pdf") else payload.title + ".pdf", file=io.BytesIO(data))
    from app.routers.documents import _upload_one

    doc = _upload_one(db, user, folder, up, title=payload.title)
    return {"id": doc.id, "title": doc.title}


# ----- RAG -----
class RagIn(BaseModel):
    query: str
    limit: int = 6


@router.post("/rag")
def rag_query(payload: RagIn, db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    from app.vectors import answer

    return answer(db, payload.query, limit=payload.limit)


@router.post("/documents/{doc_id}/embed")
def embed_doc(doc_id: int, db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    from app.vectors import index_document

    d = db.get(Document, doc_id)
    if not d:
        raise HTTPException(404, "Not found")
    n = index_document(db, d.id, d.title or "", d.extracted_text or "")
    return {"chunks": n}


# ----- Cases / BPMN -----
class CaseIn(BaseModel):
    name: str
    document_ids: list[int] | None = None
    bpmn_id: int | None = None
    data: dict | None = None


@router.get("/cases")
def list_cases(db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    return db.query(Case).order_by(Case.created_at.desc()).all()


@router.post("/cases")
def create_case(payload: CaseIn, db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    row = Case(name=payload.name, bpmn_id=payload.bpmn_id, data=payload.data or {}, created_by=user.id)
    db.add(row)
    db.flush()
    for did in payload.document_ids or []:
        db.add(CaseDocument(case_id=row.id, document_id=did))
        d = db.get(Document, did)
        if d:
            d.case_id = row.id
    db.commit()
    db.refresh(row)
    if row.bpmn_id:
        try:
            _start_case_bpmn(db, row, user)
        except Exception:
            pass
    db.refresh(row)
    return {"id": row.id, "name": row.name, "status": row.status, "bpmn_id": row.bpmn_id, "data": row.data or {}}


def _start_case_bpmn(db: Session, case: Case, user: User) -> dict | None:
    from app.models import WorkflowTemplate
    from app.routers.workflow import start_workflow_internal

    bpmn = db.get(BpmnDefinition, case.bpmn_id)
    if not bpmn:
        return None
    tpl = db.query(WorkflowTemplate).filter(WorkflowTemplate.name == f"bpmn:{bpmn.id}").first()
    if not tpl:
        nodes = (bpmn.graph or {}).get("nodes") or []
        steps = [
            {
                "name": n.get("name") or n.get("id") or "Task",
                "assignee_role": n.get("assignee_role") or "admin",
                "assignee_id": n.get("assignee_id"),
                "due_days": n.get("due_days") or 3,
            }
            for n in nodes
            if (n.get("type") or "") in ("userTask", "task")
        ]
        if not steps:
            steps = [{"name": "Review", "assignee_role": "admin", "due_days": 3}]
        tpl = WorkflowTemplate(name=f"bpmn:{bpmn.id}", description=bpmn.name, steps=steps, graph=bpmn.graph or {}, created_by=user.id)
        db.add(tpl)
        db.flush()
    inst_ids = []
    docs = db.query(CaseDocument).filter(CaseDocument.case_id == case.id).all()
    for cd in docs:
        try:
            inst = start_workflow_internal(db, cd.document_id, tpl.id, user.id)
            inst_ids.append(inst.id)
        except Exception:
            continue
    data = dict(case.data or {})
    data["workflow_instances"] = inst_ids
    data["template_id"] = tpl.id
    case.data = data
    if inst_ids:
        case.status = "running"
    db.commit()
    return data


@router.post("/cases/{case_id}/start")
def start_case(case_id: int, db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    row = db.get(Case, case_id)
    if not row:
        raise HTTPException(404, "Case not found")
    if not row.bpmn_id:
        raise HTTPException(400, "Case has no BPMN process")
    data = _start_case_bpmn(db, row, user)
    return {"ok": True, "case_id": row.id, "status": row.status, "data": data}


@router.post("/bpmn")
def upload_bpmn(name: str = Form(...), xml: str = Form(...), db: Session = Depends(get_db), user: User = Depends(require_role("superadmin", "admin", "manager"))):
    from app.bpmn import parse_bpmn_xml

    definition = parse_bpmn_xml(xml)
    graph = {
        "name": definition.name,
        "nodes": [{"id": n.id, "type": n.type, "name": n.name, "assignee_role": n.assignee_role} for n in definition.nodes.values()],
        "edges": [{"from": e.source, "to": e.target, "condition": e.condition} for src, edges in definition.outgoing.items() for e in edges],
    }
    row = BpmnDefinition(name=name or definition.name, xml=xml, graph=graph, created_by=user.id)
    db.add(row)
    db.commit()
    db.refresh(row)
    return {"id": row.id, "name": row.name, "graph": graph}


@router.get("/bpmn")
def list_bpmn(db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    return [{"id": r.id, "name": r.name, "graph": r.graph} for r in db.query(BpmnDefinition).all()]


# ----- Reading confirmations -----
@router.post("/documents/{doc_id}/confirm-read")
def confirm_read(doc_id: int, note: str = "", db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    d = db.get(Document, doc_id)
    if not d:
        raise HTTPException(404, "Not found")
    row = ReadingConfirmation(document_id=doc_id, user_id=user.id, note=note)
    db.add(row)
    db.commit()
    return {"ok": True, "id": row.id}


@router.get("/documents/{doc_id}/reading-confirmations")
def list_reads(doc_id: int, db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    return db.query(ReadingConfirmation).filter(ReadingConfirmation.document_id == doc_id).all()


# ----- Cluster / compliance / security -----
@router.get("/cluster")
def cluster_status(user: User = Depends(require_role("superadmin", "admin"))):
    from app.cluster import members, node_id

    return {"self": node_id(), "members": members()}


@router.get("/compliance")
def compliance_status(db: Session = Depends(get_db), user: User = Depends(require_role("superadmin", "admin"))):
    from app.compliance import control_posture

    return control_posture(db)


@router.get("/compliance/gdpr/{user_id}")
def gdpr_export_user(user_id: int, db: Session = Depends(get_db), user: User = Depends(require_role("superadmin", "admin"))):
    from fastapi.responses import FileResponse
    from app.compliance import gdpr_export

    dest = doc_storage_dir(0).parent / "exports" / f"gdpr_{user_id}.zip"
    gdpr_export(db, user_id, dest)
    return FileResponse(dest, filename=dest.name, media_type="application/zip")


@router.post("/compliance/gdpr/{user_id}/erase")
def gdpr_erase_user(user_id: int, db: Session = Depends(get_db), actor: User = Depends(require_role("superadmin", "admin"))):
    from app.compliance import gdpr_erase

    target = db.get(User, user_id)
    if not target:
        raise HTTPException(404, "User not found")
    try:
        return gdpr_erase(db, target)
    except ValueError as exc:
        raise HTTPException(423, str(exc)) from exc


@router.get("/security-policy")
def get_policy(db: Session = Depends(get_db), user: User = Depends(require_role("superadmin", "admin"))):
    from app.security_policy import load_policy

    return load_policy(db)


@router.put("/security-policy")
def put_policy(payload: dict, db: Session = Depends(get_db), user: User = Depends(require_role("superadmin", "admin"))):
    row = db.get(SystemSetting, "security_policy")
    if not row:
        row = SystemSetting(key="security_policy", value=json.dumps(payload))
        db.add(row)
    else:
        row.value = json.dumps(payload)
        row.updated_at = now()
    db.commit()
    audit(db, user, "SECURITY_POLICY", "system", None, "updated")
    return payload


# ----- Reports -----
class ReportIn(BaseModel):
    name: str
    query: str = ""
    group_by: str | None = None


@router.get("/report-definitions")
def list_report_defs(db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    return db.query(ReportDefinition).filter(ReportDefinition.created_by == user.id).all()


@router.post("/report-definitions")
def create_report_def(payload: ReportIn, db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    row = ReportDefinition(name=payload.name, query=payload.query, group_by=payload.group_by, created_by=user.id)
    db.add(row)
    db.commit()
    db.refresh(row)
    return row


@router.get("/report-definitions/{rid}/run")
def run_report(rid: int, db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    from collections import Counter
    from app.querylang import apply_filters, parse_query

    row = db.get(ReportDefinition, rid)
    if not row:
        raise HTTPException(404, "Not found")
    parsed = parse_query(row.query or "")
    q = apply_filters(db.query(Document).filter(Document.deleted_at.is_(None)), parsed, db)
    docs = q.limit(2000).all()
    grouped: dict[str, int] = {}
    if row.group_by == "status":
        grouped = dict(Counter(d.status or "none" for d in docs))
    elif row.group_by == "source":
        grouped = dict(Counter(d.source or "upload" for d in docs))
    else:
        grouped = {"count": len(docs)}
    return {"name": row.name, "count": len(docs), "groups": grouped, "ids": [d.id for d in docs[:200]]}


# ----- Connectors -----
class ConnectorIn(BaseModel):
    kind: str
    name: str
    config: dict | None = None


@router.get("/connectors")
def list_connectors(db: Session = Depends(get_db), user: User = Depends(require_role("superadmin", "admin"))):
    return db.query(ConnectorAccount).all()


@router.post("/connectors")
def create_connector(payload: ConnectorIn, db: Session = Depends(get_db), user: User = Depends(require_role("superadmin", "admin"))):
    row = ConnectorAccount(kind=payload.kind, name=payload.name, config=payload.config or {}, created_by=user.id)
    db.add(row)
    db.commit()
    db.refresh(row)
    return row


@router.post("/connectors/docusign/send")
def docusign_send(doc_id: int = Form(...), email: str = Form(...), name: str = Form("Signer"), db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    from app.connectors import docusign_send as send

    d = db.get(Document, doc_id)
    _writable(db, user, d)
    acct = db.query(ConnectorAccount).filter(ConnectorAccount.kind == "docusign", ConnectorAccount.enabled.is_(True)).first()
    return send((acct.config if acct else {}) or {}, _pdf_path(d), email, name)


@router.get("/connectors/onlyoffice/{doc_id}")
def onlyoffice_cfg(doc_id: int, request: Request, db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    from app.connectors import onlyoffice_config

    d = db.get(Document, doc_id)
    if not d:
        raise HTTPException(404, "Not found")
    base = str(request.base_url).rstrip("/")
    key = f"doc-{d.id}-v{d.current_version}-{d.collab_rev or 0}"
    cfg = onlyoffice_config(
        d.id,
        d.name,
        f"{base}/api/documents/{d.id}/download",
        f"{base}/api/onlyoffice/callback?doc_id={d.id}",
        key,
    )
    acct = db.query(ConnectorAccount).filter(ConnectorAccount.kind == "onlyoffice", ConnectorAccount.enabled.is_(True)).first()
    server = ((acct.config if acct else {}) or {}).get("url") or getattr(settings, "onlyoffice_url", "") or ""
    cfg["documentServerUrl"] = server
    return cfg


@open_ent.post("/api/onlyoffice/callback")
async def onlyoffice_callback(request: Request, doc_id: int, db: Session = Depends(get_db)):
    body = await request.json()
    status_code = int(body.get("status") or 0)
    url = body.get("url")
    if status_code in (2, 6) and url:
        import httpx

        d = db.get(Document, doc_id)
        if d:
            r = httpx.get(url, timeout=60)
            r.raise_for_status()
            dest = doc_storage_dir(d.id) / f"v{d.current_version + 1}{Path(d.name).suffix or '.docx'}"
            dest.write_bytes(r.content)
            d.current_version += 1
            d.file_path = str(dest)
            d.size = dest.stat().st_size
            d.collab_rev = (d.collab_rev or 0) + 1
            db.commit()
    return {"error": 0}


@router.get("/connectors/gdrive/files")
def gdrive_files(q: str = "", db: Session = Depends(get_db), user: User = Depends(require_role("superadmin", "admin"))):
    from app.connectors import gdrive_list

    acct = db.query(ConnectorAccount).filter(ConnectorAccount.kind == "gdrive", ConnectorAccount.enabled.is_(True)).first()
    token = ((acct.config if acct else {}) or {}).get("access_token") or ""
    if not token:
        return []
    return gdrive_list(token, q)


@router.post("/connectors/gdrive/import")
def gdrive_import(file_id: str = Form(...), folder_id: int = Form(...), db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    from app.connectors import gdrive_download

    acct = db.query(ConnectorAccount).filter(ConnectorAccount.kind == "gdrive", ConnectorAccount.enabled.is_(True)).first()
    token = ((acct.config if acct else {}) or {}).get("access_token") or ""
    if not token:
        raise HTTPException(400, "Google Drive connector has no access_token")
    folder = db.get(Folder, folder_id)
    tmp = doc_storage_dir(0) / f"gdrive_{file_id}"
    gdrive_download(token, file_id, tmp)
    from starlette.datastructures import UploadFile as StarUpload
    from app.routers.documents import _upload_one

    up = StarUpload(filename=tmp.name, file=io.BytesIO(tmp.read_bytes()))
    return _upload_one(db, user, folder, up, title=tmp.name)


@router.post("/connectors/gcal/sync")
def gcal_sync(db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    import httpx
    from app.models import CalendarEvent

    acct = db.query(ConnectorAccount).filter(ConnectorAccount.kind == "gcal", ConnectorAccount.enabled.is_(True)).first()
    token = ((acct.config if acct else {}) or {}).get("access_token") or ""
    events = db.query(CalendarEvent).filter(CalendarEvent.created_by == user.id).limit(50).all()
    pushed = 0
    if token:
        for ev in events:
            httpx.post(
                "https://www.googleapis.com/calendar/v3/calendars/primary/events",
                headers={"Authorization": f"Bearer {token}"},
                json={"summary": ev.title, "description": ev.description or "", "start": {"dateTime": ev.start_at.isoformat() + "Z"}, "end": {"dateTime": (ev.end_at or ev.start_at).isoformat() + "Z"}},
                timeout=15,
            )
            pushed += 1
    return {"local": len(events), "pushed": pushed}


@router.get("/connectors/outlook/mail")
def outlook_mail(top: int = 20, db: Session = Depends(get_db), user: User = Depends(require_role("superadmin", "admin"))):
    from app.connectors import graph_list_mail

    acct = db.query(ConnectorAccount).filter(ConnectorAccount.kind == "outlook", ConnectorAccount.enabled.is_(True)).first()
    if not acct:
        raise HTTPException(400, "No Outlook / Graph connector configured")
    return graph_list_mail(acct.config or {}, top=top)


@router.post("/connectors/outlook/import")
def outlook_import(message_id: str = Form(...), folder_id: int = Form(...), db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    from app.connectors import graph_download_mime
    from app.smtp_gateway import ingest_rfc822

    folder = db.get(Folder, folder_id)
    if not folder:
        raise HTTPException(404, "Folder not found")
    acct = db.query(ConnectorAccount).filter(ConnectorAccount.kind == "outlook", ConnectorAccount.enabled.is_(True)).first()
    if not acct:
        raise HTTPException(400, "No Outlook / Graph connector configured")
    tmp = doc_storage_dir(0) / f"graph_{secrets.token_hex(6)}.eml"
    graph_download_mime(acct.config or {}, message_id, tmp)
    ids = ingest_rfc822(tmp.read_bytes(), folder_id=folder.id, user_id=user.id)
    tmp.unlink(missing_ok=True)
    return {"imported": ids}


@router.get("/documents/{doc_id}/page-image")
def page_image(doc_id: int, page: int = 1, db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    d = db.get(Document, doc_id)
    if not d:
        raise HTTPException(404, "Not found")
    f = db.get(Folder, d.folder_id)
    if not has_permission(db, user, "read", f, d):
        raise HTTPException(403)
    path = _pdf_path(d) if d.pdf_file_path or (d.file_path and str(d.file_path).lower().endswith(".pdf")) else Path(d.file_path or "")
    if not path.exists():
        raise HTTPException(404, "No file")
    try:
        import io
        import pypdfium2 as pdfium

        doc = pdfium.PdfDocument(str(path))
        try:
            idx = max(0, min(page - 1, len(doc) - 1))
            bitmap = doc[idx].render(scale=1.5)
            im = bitmap.to_pil()
            buf = io.BytesIO()
            im.save(buf, format="PNG")
            return Response(buf.getvalue(), media_type="image/png")
        finally:
            doc.close()
    except Exception as exc:
        raise HTTPException(400, f"Cannot render page: {exc}") from exc


@router.post("/documents/{doc_id}/office-link")
def office_link(doc_id: int, request: Request, db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    from app.models import ShareLink

    d = db.get(Document, doc_id)
    if not d:
        raise HTTPException(404, "Not found")
    f = db.get(Folder, d.folder_id)
    if not has_permission(db, user, "read", f, d):
        raise HTTPException(403)
    token = secrets.token_urlsafe(16)
    row = ShareLink(token=token, document_id=d.id, created_by=user.id, kind="download", name="office-edit", max_downloads=8)
    db.add(row)
    db.commit()
    base = str(request.base_url).rstrip("/")
    url = f"{base}/api/shares/{token}"
    ext = Path(d.name or "").suffix.lower()
    proto = "ms-word"
    if ext in (".xls", ".xlsx", ".csv"):
        proto = "ms-excel"
    elif ext in (".ppt", ".pptx"):
        proto = "ms-powerpoint"
    return {"url": url, "protocol": f"{proto}:ofe|u|{url}", "ext": ext, "webdav": f"{base}/webdav/{d.name}"}


@router.get("/smtp-gateway")
def smtp_gateway_status(user: User = Depends(require_role("superadmin", "admin"))):
    from app.smtp_gateway import _thread

    return {
        "enabled": bool(settings.smtp_gateway_enabled),
        "host": settings.smtp_gateway_host,
        "port": settings.smtp_gateway_port,
        "running": bool(_thread and _thread.is_alive()),
    }


# ----- Live collab -----
class CollabIn(BaseModel):
    op: dict
    rev: int | None = None


@router.post("/documents/{doc_id}/collab")
def collab_op(doc_id: int, payload: CollabIn, db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    d = db.get(Document, doc_id)
    _writable(db, user, d)
    d.collab_rev = (d.collab_rev or 0) + 1
    row = CollabOp(document_id=doc_id, rev=d.collab_rev, user_id=user.id, op=payload.op)
    if payload.op.get("notes") is not None:
        d.notes = str(payload.op.get("notes"))
    db.add(row)
    db.commit()
    return {"rev": d.collab_rev}


@router.get("/documents/{doc_id}/collab")
def collab_since(doc_id: int, since: int = 0, db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    rows = (
        db.query(CollabOp)
        .filter(CollabOp.document_id == doc_id, CollabOp.rev > since)
        .order_by(CollabOp.rev)
        .all()
    )
    return [{"rev": r.rev, "op": r.op, "user_id": r.user_id} for r in rows]


# ----- Scan / CSV / ZIP -----
@router.post("/scan/ingest")
def scan_ingest(folder_id: int = Form(...), title: str | None = Form(None), file: UploadFile = File(...), db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    from app.routers.documents import _upload_one

    folder = db.get(Folder, folder_id)
    if not folder:
        raise HTTPException(404, "Folder not found")
    d = _upload_one(db, user, folder, file, title=title or file.filename, tags="scan")
    d.source = "scan"
    db.commit()
    return d


@router.post("/import/csv")
def import_csv(folder_id: int = Form(...), file: UploadFile = File(...), db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    folder = db.get(Folder, folder_id)
    if not folder:
        raise HTTPException(404, "Folder not found")
    raw = file.file.read()
    text = raw.decode("utf-8-sig", errors="replace")
    reader = csv.DictReader(io.StringIO(text))
    created = 0
    from app.models import DocumentVersion

    for row in reader:
        title = (row.get("title") or row.get("name") or "imported").strip()
        tags = (row.get("tags") or "").strip()
        payload = {k: v for k, v in row.items() if k not in ("title", "name", "tags")}
        d = Document(
            name=f"{title}.json",
            title=title,
            folder_id=folder.id,
            tags=tags,
            metadata_json=payload,
            created_by=user.id,
            mime="application/json",
            file_path="",
            source="csv",
        )
        db.add(d)
        db.flush()
        path = doc_storage_dir(d.id) / "v1.json"
        path.write_text(json.dumps(payload, indent=2), encoding="utf-8")
        d.file_path = str(path)
        d.size = path.stat().st_size
        db.add(DocumentVersion(document_id=d.id, version_number=1, file_path=str(path), size=d.size, created_by=user.id, comment="CSV import"))
        created += 1
    db.commit()
    return {"created": created}


@router.post("/import/zip")
def import_zip(folder_id: int = Form(...), file: UploadFile = File(...), db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    from app.routers.documents import _upload_one
    from starlette.datastructures import UploadFile as StarUpload

    folder = db.get(Folder, folder_id)
    data = file.file.read()
    created = []
    with zipfile.ZipFile(io.BytesIO(data)) as zf:
        for info in zf.infolist():
            if info.is_dir() or info.filename.startswith("__"):
                continue
            payload = zf.read(info)
            up = StarUpload(filename=Path(info.filename).name, file=io.BytesIO(payload))
            created.append(_upload_one(db, user, folder, up, title=Path(info.filename).stem))
    return {"created": [c.id for c in created]}


# ----- SAP ArchiveLink -----
def _al_auth(request: Request, db: Session) -> None:
    secret = settings.archivelink_secret
    if not secret:
        return
    token = request.headers.get("x-archive-key") or request.query_params.get("pVersion") or ""
    if token != secret:
        raise HTTPException(401, "ArchiveLink authentication failed")


@open_ent.api_route("/archivelink/{cont_rep}/{doc_id}", methods=["PUT", "GET", "HEAD", "DELETE"])
async def archivelink_item(cont_rep: str, doc_id: str, request: Request, db: Session = Depends(get_db)):
    _al_auth(request, db)
    row = (
        db.query(ArchiveLinkEntry)
        .filter(ArchiveLinkEntry.cont_rep == cont_rep, ArchiveLinkEntry.doc_id == doc_id)
        .first()
    )
    if request.method == "PUT":
        body = await request.body()
        dest_dir = doc_storage_dir(0).parent / "archivelink" / cont_rep
        dest_dir.mkdir(parents=True, exist_ok=True)
        dest = dest_dir / f"{doc_id}.bin"
        dest.write_bytes(body)
        if not row:
            row = ArchiveLinkEntry(cont_rep=cont_rep, doc_id=doc_id)
            db.add(row)
        row.file_path = str(dest)
        row.size = len(body)
        row.mime = request.headers.get("content-type") or "application/octet-stream"
        mapping = {}
        s = db.get(SystemSetting, "archivelink")
        if s and s.value:
            try:
                mapping = json.loads(s.value)
            except json.JSONDecodeError:
                mapping = {}
        fid = mapping.get(cont_rep) or mapping.get(str(cont_rep))
        if fid and not row.document_id:
            folder = db.get(Folder, int(fid))
            owner = db.query(User).filter(User.role.in_(["superadmin", "admin"])).first()
            if folder and owner:
                from starlette.datastructures import UploadFile as StarUpload
                from app.routers.documents import _upload_one

                ext = ".bin"
                mime = row.mime or ""
                if "pdf" in mime:
                    ext = ".pdf"
                elif "text" in mime:
                    ext = ".txt"
                up = StarUpload(filename=f"{doc_id}{ext}", file=io.BytesIO(body))
                doc = _upload_one(db, owner, folder, up, title=f"ArchiveLink {cont_rep}/{doc_id}")
                row.document_id = doc.id
        db.commit()
        return Response(status_code=201, headers={"X-docId": doc_id, "X-contRep": cont_rep})
    if not row or not row.file_path:
        raise HTTPException(404, "Not found")
    if request.method == "DELETE":
        Path(row.file_path).unlink(missing_ok=True)
        db.delete(row)
        db.commit()
        return {"ok": True}
    if request.method == "HEAD":
        return Response(headers={"Content-Length": str(row.size or 0), "Content-Type": row.mime or "application/octet-stream"})
    from fastapi.responses import FileResponse

    return FileResponse(row.file_path, media_type=row.mime or "application/octet-stream")


@open_ent.get("/archivelink/{cont_rep}/{doc_id}/info")
def archivelink_info(cont_rep: str, doc_id: str, request: Request, db: Session = Depends(get_db)):
    _al_auth(request, db)
    row = (
        db.query(ArchiveLinkEntry)
        .filter(ArchiveLinkEntry.cont_rep == cont_rep, ArchiveLinkEntry.doc_id == doc_id)
        .first()
    )
    if not row:
        raise HTTPException(404, "Not found")
    return {"contRep": row.cont_rep, "docId": row.doc_id, "size": row.size, "mime": row.mime, "created_at": row.created_at}


# ----- SAML -----
@open_ent.get("/api/auth/saml/login")
def saml_login(db: Session = Depends(get_db)):
    from app.saml import authn_request_redirect

    return RedirectResponse(authn_request_redirect(db))


@open_ent.post("/api/auth/saml/acs")
async def saml_acs(request: Request, db: Session = Depends(get_db)):
    from app.saml import consume

    form = await request.form()
    user = consume(db, str(form.get("SAMLResponse") or ""), str(form.get("RelayState") or ""))
    token = create_access_token({"sub": user.username, "role": user.role})
    resp = RedirectResponse("/", status_code=303)
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
