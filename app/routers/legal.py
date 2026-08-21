"""Legal Practice Management & Corporate Legal API endpoints."""
from __future__ import annotations

from datetime import datetime, timedelta
import secrets
from typing import Any

from fastapi import APIRouter, Depends, File, Form, HTTPException, Query, UploadFile, status
from sqlalchemy.orm import Session

from app.security import get_current_user, get_password_hash, verify_password
from app.bates import apply_bates_production
from app.database import get_db, now
from app.efiling_packager import create_efiling_package
from app.email_filing import parse_and_file_email
from app.legal_assembly import assemble_document, ensure_default_templates
from app.legal_compare import compare_documents
from app.legal_matter_engine import (
    attach_document_to_matter,
    create_matter,
    enforce_ethical_wall,
    is_user_walled,
    set_ethical_wall,
)
from app.models import (
    BatesProduction,
    Document,
    EthicalWall,
    LegalTemplate,
    Matter,
    MatterDocument,
    SecureExtranetPortal,
    User,
)
from app.redaction import execute_document_redaction
from app.schemas import (
    BatesApplyRequest,
    BatesProductionOut,
    EFilingPackageRequest,
    EthicalWallCreate,
    EthicalWallOut,
    LegalAssemblyRequest,
    LegalCompareRequest,
    LegalTemplateCreate,
    LegalTemplateOut,
    MatterCreate,
    MatterDocumentAttach,
    MatterDocumentOut,
    MatterOut,
    MatterUpdate,
    PermanentRedactRequest,
    SecurePortalCreate,
    SecurePortalOut,
)

router = APIRouter(prefix="/api/legal", tags=["legal"])


# =============================================================================
# 1. Matter Management
# =============================================================================


@router.post("/matters", response_model=MatterOut)
def api_create_matter(
    payload: MatterCreate,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    return create_matter(
        db=db,
        user=user,
        matter_number=payload.matter_number,
        title=payload.title,
        client_name=payload.client_name,
        client_id=payload.client_id,
        practice_area=payload.practice_area,
        lead_attorney_id=payload.lead_attorney_id,
        court_name=payload.court_name,
        case_caption=payload.case_caption,
        judge_name=payload.judge_name,
        opposing_counsel=payload.opposing_counsel,
        billing_code=payload.billing_code,
        description=payload.description,
        metadata_json=payload.metadata_json,
    )


@router.get("/matters", response_model=list[MatterOut])
def api_list_matters(
    practice_area: str | None = None,
    status: str | None = None,
    client: str | None = None,
    q: str | None = None,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    query = db.query(Matter)
    if practice_area:
        query = query.filter(Matter.practice_area.ilike(f"%{practice_area}%"))
    if status:
        query = query.filter(Matter.status == status)
    if client:
        query = query.filter(Matter.client_name.ilike(f"%{client}%"))
    if q:
        query = query.filter(
            (Matter.title.ilike(f"%{q}%"))
            | (Matter.matter_number.ilike(f"%{q}%"))
            | (Matter.client_name.ilike(f"%{q}%"))
        )

    all_matters = query.order_by(Matter.created_at.desc()).all()
    # Filter out walled matters for non-superadmins
    accessible = [m for m in all_matters if not is_user_walled(db, user.id, m.id)]
    return accessible


@router.get("/matters/{matter_id}", response_model=MatterOut)
def api_get_matter(
    matter_id: int,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    enforce_ethical_wall(db, user, matter_id)
    matter = db.get(Matter, matter_id)
    if not matter:
        raise HTTPException(status_code=404, detail="Matter not found.")
    return matter


@router.put("/matters/{matter_id}", response_model=MatterOut)
def api_update_matter(
    matter_id: int,
    payload: MatterUpdate,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    enforce_ethical_wall(db, user, matter_id)
    matter = db.get(Matter, matter_id)
    if not matter:
        raise HTTPException(status_code=404, detail="Matter not found.")

    for k, v in payload.model_dump(exclude_unset=True).items():
        setattr(matter, k, v)

    if payload.status == "closed" and not matter.closed_at:
        matter.closed_at = now()

    db.commit()
    db.refresh(matter)
    return matter


# =============================================================================
# 2. Matter Documents & Category Architecture
# =============================================================================


@router.post("/matters/{matter_id}/documents", response_model=MatterDocumentOut)
def api_attach_matter_document(
    matter_id: int,
    payload: MatterDocumentAttach,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    return attach_document_to_matter(
        db=db,
        user=user,
        matter_id=matter_id,
        document_id=payload.document_id,
        category=payload.category,
        confidentiality=payload.confidentiality,
        bates_range=payload.bates_range,
        notes=payload.notes,
        pinned=payload.pinned,
    )


@router.get("/matters/{matter_id}/documents")
def api_list_matter_documents(
    matter_id: int,
    category: str | None = None,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    enforce_ethical_wall(db, user, matter_id)
    query = db.query(MatterDocument).filter(MatterDocument.matter_id == matter_id)
    if category:
        query = query.filter(MatterDocument.category == category)

    links = query.order_by(MatterDocument.pinned.desc(), MatterDocument.added_at.desc()).all()
    results = []
    for l in links:
        doc = db.get(Document, l.document_id)
        if doc and doc.deleted_at is None:
            results.append({
                "link_id": l.id,
                "document_id": doc.id,
                "title": doc.title,
                "name": doc.name,
                "category": l.category,
                "confidentiality": l.confidentiality,
                "bates_range": l.bates_range,
                "pinned": l.pinned,
                "notes": l.notes,
                "size": doc.size,
                "mime_type": doc.mime,
                "added_at": l.added_at,
            })
    return results


# =============================================================================
# 3. Deep Email Filing (Outlook/Gmail .eml)
# =============================================================================


@router.post("/matters/{matter_id}/emails/ingest")
async def api_ingest_email(
    matter_id: int,
    file: UploadFile = File(...),
    folder_id: int = Form(1),
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    enforce_ethical_wall(db, user, matter_id)
    raw_bytes = await file.read()
    return parse_and_file_email(
        db=db,
        user=user,
        matter_id=matter_id,
        raw_bytes=raw_bytes,
        filename=file.filename or "message.eml",
        folder_id=folder_id,
    )


# =============================================================================
# 4. Automated Document Assembly
# =============================================================================


@router.get("/templates", response_model=list[LegalTemplateOut])
def api_list_templates(
    category: str | None = None,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    ensure_default_templates(db, user)
    query = db.query(LegalTemplate)
    if category:
        query = query.filter(LegalTemplate.category == category)
    return query.all()


@router.post("/templates", response_model=LegalTemplateOut)
def api_create_template(
    payload: LegalTemplateCreate,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    existing = db.query(LegalTemplate).filter(LegalTemplate.name == payload.name).first()
    if existing:
        raise HTTPException(status_code=400, detail="Template with this name already exists.")

    tpl = LegalTemplate(
        name=payload.name,
        category=payload.category,
        description=payload.description,
        content_template=payload.content_template,
        fields_schema=payload.fields_schema or [],
        created_by=user.id,
        created_at=now(),
    )
    db.add(tpl)
    db.commit()
    db.refresh(tpl)
    return tpl


@router.post("/assembly/generate")
@router.post("/assembly")
def api_assemble_document(
    payload: LegalAssemblyRequest,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    enforce_ethical_wall(db, user, payload.matter_id)
    return assemble_document(
        db=db,
        user=user,
        template_id=payload.template_id,
        matter_id=payload.matter_id,
        variables=payload.variables,
        document_title=payload.document_title,
        output_format=payload.output_format,
        folder_id=payload.folder_id,
    )


# =============================================================================
# 5. Bates Stamping & Discovery Pagination
# =============================================================================


@router.post("/bates/apply")
def api_apply_bates(
    payload: BatesApplyRequest,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    enforce_ethical_wall(db, user, payload.matter_id)
    return apply_bates_production(
        db=db,
        user=user,
        matter_id=payload.matter_id,
        document_ids=payload.document_ids,
        production_set=payload.production_set,
        prefix=payload.prefix,
        suffix=payload.suffix,
        start_number=payload.start_number,
        pad_length=payload.pad_length,
        position=payload.position,
        disclaimer_text=payload.disclaimer_text,
    )


@router.get("/matters/{matter_id}/bates-productions", response_model=list[BatesProductionOut])
def api_list_bates_productions(
    matter_id: int,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    enforce_ethical_wall(db, user, matter_id)
    return db.query(BatesProduction).filter(BatesProduction.matter_id == matter_id).all()


# =============================================================================
# 6. Document Comparison & Legal Redlining
# =============================================================================


@router.post("/compare")
def api_compare_documents(
    payload: LegalCompareRequest,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    return compare_documents(
        db=db,
        user=user,
        doc_id_a=payload.doc_id_a,
        doc_id_b=payload.doc_id_b,
        version_num_a=payload.version_num_a,
        version_num_b=payload.version_num_b,
    )


# =============================================================================
# 7. Permanent Non-Reversible Redaction
# =============================================================================


@router.post("/documents/{document_id}/redact-permanent")
def api_redact_permanent(
    document_id: int,
    payload: PermanentRedactRequest,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    return execute_document_redaction(
        db=db,
        user=user,
        document_id=document_id,
        patterns=payload.patterns,
        builtin_presets=payload.builtin_presets,
        bounding_boxes=payload.bounding_boxes,
        save_as_new=payload.save_as_new,
    )


# =============================================================================
# 8. Ethical Walls & Conflict Management
# =============================================================================


@router.post("/walls", response_model=EthicalWallOut)
def api_create_wall(
    payload: EthicalWallCreate,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    return set_ethical_wall(
        db=db,
        user=user,
        matter_id=payload.matter_id,
        walled_user_ids=payload.walled_user_ids,
        reason=payload.reason,
        walled_group_ids=payload.walled_group_ids,
        client_name=payload.client_name,
    )


@router.get("/walls", response_model=list[EthicalWallOut])
def api_list_walls(
    matter_id: int | None = None,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    query = db.query(EthicalWall)
    if matter_id:
        query = query.filter(EthicalWall.matter_id == matter_id)
    return query.all()


# =============================================================================
# 9. Court e-Filing Package Creator
# =============================================================================


@router.post("/matters/{matter_id}/efiling/package")
def api_create_efiling_package(
    matter_id: int,
    payload: EFilingPackageRequest,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    enforce_ethical_wall(db, user, matter_id)
    return create_efiling_package(
        db=db,
        user=user,
        matter_id=matter_id,
        pleading_doc_id=payload.pleading_doc_id,
        exhibit_doc_ids=payload.exhibit_doc_ids,
        package_name=payload.package_name,
        filing_jurisdiction=payload.filing_jurisdiction,
    )


# =============================================================================
# 10. Secure Client Extranet Portal
# =============================================================================


@router.post("/portals", response_model=SecurePortalOut)
def api_create_extranet_portal(
    payload: SecurePortalCreate,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    enforce_ethical_wall(db, user, payload.matter_id)
    matter = db.get(Matter, payload.matter_id)
    if not matter:
        raise HTTPException(status_code=404, detail="Matter not found.")

    token = secrets.token_urlsafe(32)
    pwd_hash = get_password_hash(payload.password) if payload.password else None
    exp = now() + timedelta(days=payload.expires_in_days) if payload.expires_in_days else None

    portal = SecureExtranetPortal(
        token=token,
        matter_id=payload.matter_id,
        document_ids=payload.document_ids,
        recipient_email=payload.recipient_email,
        recipient_name=payload.recipient_name,
        password_hash=pwd_hash,
        watermark_text=payload.watermark_text,
        allow_download=payload.allow_download,
        expires_at=exp,
        created_by=user.id,
        created_at=now(),
    )
    db.add(portal)
    db.commit()
    db.refresh(portal)
    return portal


@router.get("/portals/{token}")
def api_access_extranet_portal(
    token: str,
    password: str | None = Query(None),
    db: Session = Depends(get_db),
):
    portal = db.query(SecureExtranetPortal).filter(SecureExtranetPortal.token == token).first()
    if not portal:
        raise HTTPException(status_code=404, detail="Portal share link not found or invalid.")

    if portal.expires_at and portal.expires_at < now():
        raise HTTPException(status_code=410, detail="This secure client portal link has expired.")

    if portal.password_hash:
        if not password or not verify_password(password, portal.password_hash):
            raise HTTPException(status_code=401, detail="Password required or invalid.")

    portal.access_count = (portal.access_count or 0) + 1
    portal.last_accessed_at = now()
    db.commit()

    matter = db.get(Matter, portal.matter_id)
    docs = []
    for doc_id in (portal.document_ids or []):
        d = db.get(Document, doc_id)
        if d and d.deleted_at is None:
            docs.append({
                "id": d.id,
                "title": d.title,
                "name": d.name,
                "size": d.size,
                "mime_type": d.mime,
            })

    return {
        "status": "authorized",
        "matter_number": matter.matter_number if matter else "",
        "matter_title": matter.title if matter else "",
        "client_name": matter.client_name if matter else "",
        "recipient_name": portal.recipient_name,
        "watermark_text": portal.watermark_text,
        "allow_download": portal.allow_download,
        "documents": docs,
    }
