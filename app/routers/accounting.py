"""Accounting & Financial EDMS Router: 2/3-Way Matching, OCR, PEPPOL, Duplicate Detection, ERP & Auditor Portals."""
from __future__ import annotations

import secrets
from datetime import datetime, timedelta
from typing import Any

from fastapi import APIRouter, Depends, File, Form, HTTPException, Query, UploadFile, status
from sqlalchemy.orm import Session

from app.ap_matching_engine import perform_matching
from app.barcode_batch_engine import split_batch_by_barcode
from app.database import get_db, now
from app.duplicate_invoice_detector import detect_duplicate_invoice
from app.einvoice_validator import validate_peppol_ubl_xml
from app.erp_sync_engine import sync_invoice_to_erp
from app.invoice_ocr_parser import parse_invoice_ocr_text
from app.models import (
    AuditorPortal,
    Document,
    ERPIntegration,
    GoodsReceivedNote,
    InvoiceRecord,
    PurchaseOrder,
    User,
)
from app.schemas import (
    AuditorPortalCreate,
    AuditorPortalOut,
    GoodsReceivedNoteCreate,
    GoodsReceivedNoteOut,
    InvoiceRecordCreate,
    InvoiceRecordOut,
    PurchaseOrderCreate,
    PurchaseOrderOut,
)
from app.security import get_current_user, get_password_hash, require_role, verify_password

router = APIRouter(prefix="/api/accounting", tags=["accounting"])


# =============================================================================
# 1. Purchase Orders (PO)
# =============================================================================


@router.post("/purchase-orders", response_model=PurchaseOrderOut)
def create_purchase_order(
    payload: PurchaseOrderCreate,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    existing = db.query(PurchaseOrder).filter(PurchaseOrder.po_number == payload.po_number).first()
    if existing:
        raise HTTPException(status_code=400, detail=f"PO number '{payload.po_number}' already exists.")

    po = PurchaseOrder(
        po_number=payload.po_number,
        vendor_name=payload.vendor_name,
        total_amount=payload.total_amount,
        currency=payload.currency,
        status=payload.status,
        line_items=payload.line_items,
        created_by=user.id,
        created_at=now(),
    )
    db.add(po)
    db.commit()
    db.refresh(po)
    return po


@router.get("/purchase-orders", response_model=list[PurchaseOrderOut])
def list_purchase_orders(
    vendor: str | None = None,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    q = db.query(PurchaseOrder)
    if vendor:
        q = q.filter(PurchaseOrder.vendor_name.ilike(f"%{vendor}%"))
    return q.order_by(PurchaseOrder.created_at.desc()).all()


# =============================================================================
# 2. Goods Received Notes (GRN)
# =============================================================================


@router.post("/grns", response_model=GoodsReceivedNoteOut)
def create_goods_received_note(
    payload: GoodsReceivedNoteCreate,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    existing = db.query(GoodsReceivedNote).filter(GoodsReceivedNote.grn_number == payload.grn_number).first()
    if existing:
        raise HTTPException(status_code=400, detail=f"GRN number '{payload.grn_number}' already exists.")

    grn = GoodsReceivedNote(
        grn_number=payload.grn_number,
        po_number=payload.po_number,
        vendor_name=payload.vendor_name,
        received_date=payload.received_date or now(),
        line_items=payload.line_items,
        created_by=user.id,
        created_at=now(),
    )
    db.add(grn)
    db.commit()
    db.refresh(grn)
    return grn


@router.get("/grns", response_model=list[GoodsReceivedNoteOut])
def list_goods_received_notes(
    po_number: str | None = None,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    q = db.query(GoodsReceivedNote)
    if po_number:
        q = q.filter(GoodsReceivedNote.po_number == po_number)
    return q.order_by(GoodsReceivedNote.created_at.desc()).all()


# =============================================================================
# 3. Invoice Records & Matching
# =============================================================================


@router.post("/invoices", response_model=InvoiceRecordOut)
def create_invoice(
    payload: InvoiceRecordCreate,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    # 1. Duplicate check
    dup_eval = detect_duplicate_invoice(
        db,
        vendor_name=payload.vendor_name,
        invoice_number=payload.invoice_number,
        total_amount=payload.total_amount,
        vendor_tax_id=payload.vendor_tax_id,
        invoice_date=payload.invoice_date,
    )

    inv = InvoiceRecord(
        invoice_number=payload.invoice_number,
        vendor_name=payload.vendor_name,
        vendor_tax_id=payload.vendor_tax_id,
        po_number=payload.po_number,
        grn_number=payload.grn_number,
        subtotal=payload.subtotal,
        tax_amount=payload.tax_amount,
        total_amount=payload.total_amount,
        currency=payload.currency,
        invoice_date=payload.invoice_date,
        due_date=payload.due_date,
        gl_account=payload.gl_account,
        cost_center=payload.cost_center,
        line_items=payload.line_items,
        document_id=payload.document_id,
        is_duplicate=dup_eval["is_duplicate"],
        duplicate_of_id=dup_eval["duplicate_of_id"],
        matching_status="unmatched",
        payment_status="pending_approval",
        created_by=user.id,
        created_at=now(),
    )
    db.add(inv)
    db.commit()
    db.refresh(inv)

    # 2. Automatically execute 2-way or 3-way matching if PO is attached
    if inv.po_number:
        try:
            perform_matching(db, inv.id, user)
            db.refresh(inv)
        except Exception:
            pass

    return inv


@router.get("/invoices", response_model=list[InvoiceRecordOut])
def list_invoices(
    matching_status: str | None = None,
    payment_status: str | None = None,
    vendor: str | None = None,
    gl_account: str | None = None,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    q = db.query(InvoiceRecord)
    if matching_status:
        q = q.filter(InvoiceRecord.matching_status == matching_status)
    if payment_status:
        q = q.filter(InvoiceRecord.payment_status == payment_status)
    if vendor:
        q = q.filter(InvoiceRecord.vendor_name.ilike(f"%{vendor}%"))
    if gl_account:
        q = q.filter(InvoiceRecord.gl_account == gl_account)
    return q.order_by(InvoiceRecord.created_at.desc()).all()


@router.get("/invoices/{invoice_id}", response_model=InvoiceRecordOut)
def get_invoice(
    invoice_id: int,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    inv = db.get(InvoiceRecord, invoice_id)
    if not inv:
        raise HTTPException(status_code=404, detail="Invoice record not found.")
    return inv


@router.post("/invoices/{invoice_id}/match")
def api_match_invoice(
    invoice_id: int,
    price_tolerance_pct: float = Query(2.0, ge=0.0, le=50.0),
    qty_tolerance_pct: float = Query(0.0, ge=0.0, le=50.0),
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    try:
        return perform_matching(
            db,
            invoice_id,
            user,
            price_tolerance_pct=price_tolerance_pct,
            qty_tolerance_pct=qty_tolerance_pct,
        )
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))


@router.post("/invoices/extract-ocr")
def api_extract_invoice_ocr(
    payload: dict[str, Any],
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    text = payload.get("text", "")
    document_id = payload.get("document_id")
    if not text and document_id:
        doc = db.get(Document, document_id)
        if doc and doc.extracted_text:
            text = doc.extracted_text

    return parse_invoice_ocr_text(text)


@router.post("/invoices/check-duplicate")
def api_check_duplicate_invoice(
    payload: dict[str, Any],
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    vendor_name = payload.get("vendor_name", "")
    invoice_number = payload.get("invoice_number", "")
    total_amount = float(payload.get("total_amount", 0.0))
    vendor_tax_id = payload.get("vendor_tax_id")
    invoice_id = payload.get("invoice_id")

    return detect_duplicate_invoice(
        db,
        vendor_name=vendor_name,
        invoice_number=invoice_number,
        total_amount=total_amount,
        vendor_tax_id=vendor_tax_id,
        current_invoice_id=invoice_id,
    )


# =============================================================================
# 4. E-Invoicing (PEPPOL / UBL XML)
# =============================================================================


@router.post("/einvoice/validate")
async def api_validate_einvoice(
    file: UploadFile = File(...),
    user: User = Depends(get_current_user),
):
    content = await file.read()
    return validate_peppol_ubl_xml(content)


# =============================================================================
# 5. Batch Barcode / QR Separator Splitting
# =============================================================================


@router.post("/batch-split")
async def api_split_batch(
    folder_id: int = Form(...),
    batch_name: str = Form("Batch_Scan"),
    file: UploadFile = File(...),
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    pdf_bytes = await file.read()
    results = split_batch_by_barcode(
        db=db,
        user=user,
        pdf_bytes=pdf_bytes,
        folder_id=folder_id,
        batch_name=batch_name,
    )
    return {
        "status": "success",
        "batch_name": batch_name,
        "split_documents_count": len(results),
        "documents": results,
    }


# =============================================================================
# 6. ERP & GL Synchronization
# =============================================================================


@router.post("/invoices/{invoice_id}/erp-sync")
def api_sync_erp(
    invoice_id: int,
    payload: dict[str, Any],
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    platform = payload.get("platform", "sap")
    gl_account = payload.get("gl_account")
    cost_center = payload.get("cost_center")

    try:
        return sync_invoice_to_erp(
            db,
            user,
            invoice_id=invoice_id,
            platform=platform,
            gl_account=gl_account,
            cost_center=cost_center,
        )
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))


# =============================================================================
# 7. Read-Only Auditor Portals
# =============================================================================


@router.post("/auditor-portals", response_model=AuditorPortalOut)
def create_auditor_portal(
    payload: AuditorPortalCreate,
    db: Session = Depends(get_db),
    user: User = Depends(require_role("superadmin", "admin", "finance", "compliance")),
):
    token = secrets.token_urlsafe(24)
    pwd_hash = get_password_hash(payload.password)
    expires_at = now() + timedelta(days=payload.expires_in_days)

    portal = AuditorPortal(
        token=token,
        auditor_name=payload.auditor_name,
        auditor_email=payload.auditor_email,
        firm_name=payload.firm_name or "Independent Audit Firm",
        sample_document_ids=payload.sample_document_ids,
        allowed_gl_accounts=payload.allowed_gl_accounts,
        password_hash=pwd_hash,
        expires_at=expires_at,
        created_by=user.id,
        created_at=now(),
    )
    db.add(portal)
    db.commit()
    db.refresh(portal)
    return portal


@router.post("/auditor-portals/{token}/access")
def access_auditor_portal(
    token: str,
    payload: dict[str, Any],
    db: Session = Depends(get_db),
):
    password = payload.get("password", "")
    portal = db.query(AuditorPortal).filter(AuditorPortal.token == token).first()
    if not portal:
        raise HTTPException(status_code=404, detail="Auditor portal not found.")

    if portal.expires_at and portal.expires_at < now():
        raise HTTPException(status_code=403, detail="Auditor portal access has expired.")

    if not verify_password(password, portal.password_hash or ""):
        raise HTTPException(status_code=401, detail="Invalid auditor portal credentials.")

    portal.access_count += 1
    portal.last_accessed_at = now()
    db.commit()

    sample_docs = []
    for doc_id in (portal.sample_document_ids or []):
        d = db.get(Document, doc_id)
        if d and d.deleted_at is None:
            sample_docs.append({
                "id": d.id,
                "title": d.title,
                "name": d.name,
                "size": d.size,
                "mime_type": d.mime,
                "created_at": d.created_at,
                "tags": d.tags,
            })

    return {
        "status": "authorized",
        "auditor_name": portal.auditor_name,
        "firm_name": portal.firm_name,
        "sample_documents": sample_docs,
        "allowed_gl_accounts": portal.allowed_gl_accounts,
        "expires_at": portal.expires_at,
    }
