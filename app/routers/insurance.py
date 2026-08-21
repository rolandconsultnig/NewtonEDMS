"""Insurance & Claims EDMS Router: Policies, Claims, IDP Extraction, Fraud Detection & External Portals."""
from __future__ import annotations

import secrets
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any

from fastapi import APIRouter, Depends, File, Form, HTTPException, Query, UploadFile, status
from fastapi.responses import Response
from sqlalchemy.orm import Session

from app.claims_idp_parser import parse_medical_record, parse_police_report, parse_repair_estimate
from app.database import BASE_DIR, get_db, now
from app.insurance_document_generator import generate_settlement_statement_pdf
from app.insurance_engine import adjudicate_claim
from app.insurance_fraud_detector import analyze_image_exif_and_fraud
from app.models import (
    ClaimEvidence,
    ClaimPortalShare,
    Document,
    InsuranceClaim,
    InsurancePolicy,
    User,
)
from app.schemas import (
    ClaimEvidenceOut,
    ClaimPortalShareCreate,
    ClaimPortalShareOut,
    InsuranceClaimCreate,
    InsuranceClaimOut,
    InsurancePolicyCreate,
    InsurancePolicyOut,
)
from app.security import get_current_user, get_password_hash, require_role, verify_password

router = APIRouter(prefix="/api/insurance", tags=["insurance"])


# =============================================================================
# 1. Insurance Policies
# =============================================================================


@router.post("/policies", response_model=InsurancePolicyOut)
def create_policy(
    payload: InsurancePolicyCreate,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    existing = db.query(InsurancePolicy).filter(InsurancePolicy.policy_number == payload.policy_number).first()
    if existing:
        raise HTTPException(status_code=400, detail=f"Policy '{payload.policy_number}' already exists.")

    policy = InsurancePolicy(
        policy_number=payload.policy_number,
        insured_name=payload.insured_name,
        policy_type=payload.policy_type,
        effective_date=payload.effective_date or now(),
        expiration_date=payload.expiration_date or (now() + timedelta(days=365)),
        premium=payload.premium,
        deductible=payload.deductible,
        coverage_limit=payload.coverage_limit,
        status=payload.status,
        master_policy_id=payload.master_policy_id,
        metadata_json=payload.metadata_json,
        created_by=user.id,
        created_at=now(),
    )
    db.add(policy)
    db.commit()
    db.refresh(policy)
    return policy


@router.get("/policies", response_model=list[InsurancePolicyOut])
def list_policies(
    policy_type: str | None = None,
    insured_name: str | None = None,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    q = db.query(InsurancePolicy)
    if policy_type:
        q = q.filter(InsurancePolicy.policy_type == policy_type)
    if insured_name:
        q = q.filter(InsurancePolicy.insured_name.ilike(f"%{insured_name}%"))
    return q.order_by(InsurancePolicy.created_at.desc()).all()


@router.get("/policies/{policy_id}", response_model=InsurancePolicyOut)
def get_policy(
    policy_id: int,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    pol = db.get(InsurancePolicy, policy_id)
    if not pol:
        raise HTTPException(status_code=404, detail="Policy not found.")
    return pol


# =============================================================================
# 2. Insurance Claims & FNOL Adjudication
# =============================================================================


@router.post("/claims", response_model=InsuranceClaimOut)
def create_claim(
    payload: InsuranceClaimCreate,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    existing = db.query(InsuranceClaim).filter(InsuranceClaim.claim_number == payload.claim_number).first()
    if existing:
        raise HTTPException(status_code=400, detail=f"Claim '{payload.claim_number}' already exists.")

    policy = db.get(InsurancePolicy, payload.policy_id)
    if not policy:
        raise HTTPException(status_code=404, detail="Referenced policy not found.")

    claim = InsuranceClaim(
        claim_number=payload.claim_number,
        policy_id=payload.policy_id,
        claimant_name=payload.claimant_name,
        loss_date=payload.loss_date or now(),
        loss_type=payload.loss_type,
        loss_location=payload.loss_location,
        estimated_loss=payload.estimated_loss,
        notes=payload.notes,
        created_by=user.id,
        created_at=now(),
    )
    db.add(claim)
    db.commit()
    db.refresh(claim)

    # Automatically execute claim adjudication and routing rules
    adjudicate_claim(db, claim, policy)
    db.refresh(claim)
    return claim


@router.get("/claims", response_model=list[InsuranceClaimOut])
def list_claims(
    status_filter: str | None = Query(None, alias="status"),
    loss_type: str | None = None,
    policy_id: int | None = None,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    q = db.query(InsuranceClaim)
    if status_filter:
        q = q.filter(InsuranceClaim.status == status_filter)
    if loss_type:
        q = q.filter(InsuranceClaim.loss_type == loss_type)
    if policy_id:
        q = q.filter(InsuranceClaim.policy_id == policy_id)
    return q.order_by(InsuranceClaim.created_at.desc()).all()


@router.get("/claims/{claim_id}", response_model=InsuranceClaimOut)
def get_claim(
    claim_id: int,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    claim = db.get(InsuranceClaim, claim_id)
    if not claim:
        raise HTTPException(status_code=404, detail="Claim not found.")
    return claim


@router.post("/claims/{claim_id}/adjudicate")
def api_adjudicate_claim(
    claim_id: int,
    auto_approval_threshold: float = Query(1500.0, ge=0.0),
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    claim = db.get(InsuranceClaim, claim_id)
    if not claim:
        raise HTTPException(status_code=404, detail="Claim not found.")
    policy = db.get(InsurancePolicy, claim.policy_id)
    if not policy:
        raise HTTPException(status_code=404, detail="Policy not found.")

    return adjudicate_claim(db, claim, policy, auto_approval_threshold=auto_approval_threshold)


# =============================================================================
# 3. Multi-Format Evidence Ingestion & EXIF Fraud Analysis
# =============================================================================


@router.post("/claims/{claim_id}/evidence", response_model=ClaimEvidenceOut)
async def upload_claim_evidence(
    claim_id: int,
    evidence_type: str = Form("scene_photo"),
    notes: str = Form(""),
    folder_id: int = Form(...),
    file: UploadFile = File(...),
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    claim = db.get(InsuranceClaim, claim_id)
    if not claim:
        raise HTTPException(status_code=404, detail="Claim not found.")

    content = await file.read()

    # Save to storage
    rel_path = f"insurance/{claim.claim_number}/{file.filename}"
    target = BASE_DIR / "storage" / rel_path
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_bytes(content)

    doc = Document(
        name=file.filename or "evidence.jpg",
        title=f"Evidence - {claim.claim_number} - {evidence_type.title()}",
        file_path=str(rel_path).replace("\\", "/"),
        mime=file.content_type or "application/octet-stream",
        size=len(content),
        folder_id=folder_id,
        created_by=user.id,
        created_at=now(),
        tags=f"insurance,claim-{claim.claim_number},{evidence_type}",
        status="active",
    )
    db.add(doc)
    db.commit()
    db.refresh(doc)

    # Run EXIF Fraud and duplicate hash analysis
    fraud_eval = analyze_image_exif_and_fraud(db, claim, content, evidence_type=evidence_type)

    evidence = ClaimEvidence(
        claim_id=claim.id,
        document_id=doc.id,
        evidence_type=evidence_type,
        exif_metadata=fraud_eval["exif"],
        image_hash=fraud_eval["image_hash"],
        is_fraud_flagged=fraud_eval["is_fraud_flagged"],
        notes=notes or f"Uploaded by {user.username}",
        created_by=user.id,
        created_at=now(),
    )
    db.add(evidence)
    db.commit()
    db.refresh(evidence)
    return evidence


@router.get("/claims/{claim_id}/evidence", response_model=list[ClaimEvidenceOut])
def list_claim_evidence(
    claim_id: int,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    return db.query(ClaimEvidence).filter(ClaimEvidence.claim_id == claim_id).order_by(ClaimEvidence.created_at.desc()).all()


# =============================================================================
# 4. Intelligent Document Processing (IDP)
# =============================================================================


@router.post("/idp/extract")
def api_idp_extract(
    payload: dict[str, Any],
    user: User = Depends(get_current_user),
):
    doc_type = payload.get("doc_type", "police_report")
    text = payload.get("text", "")

    if doc_type == "police_report":
        return parse_police_report(text)
    elif doc_type == "medical_record":
        return parse_medical_record(text)
    elif doc_type == "repair_estimate":
        return parse_repair_estimate(text)
    else:
        raise HTTPException(status_code=400, detail=f"Unsupported IDP document type '{doc_type}'.")


# =============================================================================
# 5. Settlement Statement PDF Generation
# =============================================================================


@router.post("/claims/{claim_id}/generate-settlement")
def api_generate_settlement(
    claim_id: int,
    payload: dict[str, Any] = None,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    claim = db.get(InsuranceClaim, claim_id)
    if not claim:
        raise HTTPException(status_code=404, detail="Claim not found.")
    policy = db.get(InsurancePolicy, claim.policy_id)
    if not policy:
        raise HTTPException(status_code=404, detail="Policy not found.")

    custom_notes = (payload or {}).get("notes", "")
    pdf_bytes = generate_settlement_statement_pdf(claim, policy, custom_notes=custom_notes)

    return Response(
        content=pdf_bytes,
        media_type="application/pdf",
        headers={"Content-Disposition": f'attachment; filename="Settlement_{claim.claim_number}.pdf"'},
    )


# =============================================================================
# 6. Secure Adjuster & Policyholder Portals
# =============================================================================


@router.post("/portals", response_model=ClaimPortalShareOut)
def create_claim_portal(
    payload: ClaimPortalShareCreate,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    claim = db.get(InsuranceClaim, payload.claim_id)
    if not claim:
        raise HTTPException(status_code=404, detail="Claim not found.")

    token = secrets.token_urlsafe(24)
    pwd_hash = get_password_hash(payload.password)
    expires_at = now() + timedelta(days=payload.expires_in_days)

    portal = ClaimPortalShare(
        token=token,
        claim_id=claim.id,
        recipient_email=payload.recipient_email,
        recipient_name=payload.recipient_name or "Claimant",
        recipient_role=payload.recipient_role,
        password_hash=pwd_hash,
        expires_at=expires_at,
        created_by=user.id,
        created_at=now(),
    )
    db.add(portal)
    db.commit()
    db.refresh(portal)
    return portal


@router.post("/portals/{token}/access")
def access_claim_portal(
    token: str,
    payload: dict[str, Any],
    db: Session = Depends(get_db),
):
    password = payload.get("password", "")
    portal = db.query(ClaimPortalShare).filter(ClaimPortalShare.token == token).first()
    if not portal:
        raise HTTPException(status_code=404, detail="Claim portal not found.")

    if portal.expires_at and portal.expires_at < now():
        raise HTTPException(status_code=403, detail="Claim portal has expired.")

    if not verify_password(password, portal.password_hash or ""):
        raise HTTPException(status_code=401, detail="Invalid credentials for portal.")

    portal.access_count += 1
    portal.last_accessed_at = now()
    db.commit()

    claim = db.get(InsuranceClaim, portal.claim_id)
    evidences = db.query(ClaimEvidence).filter(ClaimEvidence.claim_id == portal.claim_id).all()

    return {
        "status": "authorized",
        "claim_number": claim.claim_number if claim else None,
        "recipient_role": portal.recipient_role,
        "recipient_name": portal.recipient_name,
        "claim_status": claim.status if claim else None,
        "evidence_count": len(evidences),
        "expires_at": portal.expires_at,
    }
