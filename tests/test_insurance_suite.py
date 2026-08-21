"""Automated Test Suite for Insurance & Claims Management EDMS Suite.

Validates:
1. Policy Administration & Endorsements
2. FNOL Claim Ingestion & Automated Low-Value Adjudication (<$1,500 Auto-Approval)
3. Specialized Claim Routing (Bodily Injury, High Severity Loss)
4. Intelligent Document Processing (IDP) for Police Reports, Medical Billing & Repair Estimates
5. EXIF & Duplicate Photo Cross-Claim Fraud Detection
6. Official Settlement Statement PDF Generation
7. Secure External Adjuster & Policyholder Portals
"""
from __future__ import annotations

import io
from datetime import datetime, timedelta
import pytest
from fastapi.testclient import TestClient
from PIL import Image

from app.database import now
from app.models import Document, InsuranceClaim, InsurancePolicy, User
from app.security import get_password_hash


def test_policy_creation_and_endorsements(client, admin_user):
    """Test creating master policy and child endorsements."""
    from tests.conftest import _auth, _login

    headers = _auth(_login(client, "admin", "admin123"))

    # 1. Create Master Auto Policy
    pol_res = client.post(
        "/api/insurance/policies",
        headers=headers,
        json={
            "policy_number": "POL-AUTO-2026-8800",
            "insured_name": "Alexander Vance",
            "policy_type": "auto",
            "premium": 1800.00,
            "deductible": 500.00,
            "coverage_limit": 250000.00,
            "status": "active",
        },
    )
    assert pol_res.status_code == 200, pol_res.text
    pol_data = pol_res.json()
    assert pol_data["policy_number"] == "POL-AUTO-2026-8800"
    master_id = pol_data["id"]

    # 2. Add Endorsement / Rider
    end_res = client.post(
        "/api/insurance/policies",
        headers=headers,
        json={
            "policy_number": "POL-AUTO-2026-8800-END1",
            "insured_name": "Alexander Vance",
            "policy_type": "auto",
            "premium": 250.00,
            "deductible": 250.00,
            "coverage_limit": 50000.00,
            "status": "endorsement",
            "master_policy_id": master_id,
        },
    )
    assert end_res.status_code == 200, end_res.text
    end_data = end_res.json()
    assert end_data["master_policy_id"] == master_id


def test_fnol_claim_ingestion_and_auto_approval(client, admin_user, db_session):
    """Test low-value First Notice of Loss (FNOL) auto-approval (<$1,500 threshold)."""
    from tests.conftest import _auth, _login

    headers = _auth(_login(client, "admin", "admin123"))

    # Seed active policy
    policy = InsurancePolicy(
        policy_number="POL-PROP-2026-1100",
        insured_name="Sarah Connor",
        policy_type="property",
        deductible=200.00,
        coverage_limit=500000.00,
        status="active",
        created_by=admin_user.id,
    )
    db_session.add(policy)
    db_session.commit()
    db_session.refresh(policy)

    # Submit low-value minor storm damage claim ($1,200 < $1,500 auto-approval threshold)
    claim_res = client.post(
        "/api/insurance/claims",
        headers=headers,
        json={
            "claim_number": "CLM-2026-0001",
            "policy_id": policy.id,
            "claimant_name": "Sarah Connor",
            "loss_type": "storm",
            "loss_location": "123 Cyber Way, Los Angeles, CA",
            "estimated_loss": 1200.00,
            "notes": "Minor roof shingle blown off by heavy wind.",
        },
    )
    assert claim_res.status_code == 200, claim_res.text
    claim_data = claim_res.json()
    assert claim_data["claim_number"] == "CLM-2026-0001"
    assert claim_data["auto_approved"] is True
    assert claim_data["status"] == "approved"
    # Net settlement = $1,200 - $200 deductible = $1,000
    assert claim_data["settlement_amount"] == 1000.00


def test_specialized_claims_routing(client, admin_user, db_session):
    """Test routing complex claims: Bodily Injury and Large Commercial Losses."""
    from tests.conftest import _auth, _login

    headers = _auth(_login(client, "admin", "admin123"))

    policy = InsurancePolicy(
        policy_number="POL-COMM-2026-5500",
        insured_name="Metropolis Warehouse LLC",
        policy_type="commercial",
        deductible=5000.00,
        coverage_limit=2000000.00,
        status="active",
        created_by=admin_user.id,
    )
    db_session.add(policy)
    db_session.commit()
    db_session.refresh(policy)

    # 1. Bodily Injury Claim (Must route to specialized medical review, never auto-approved)
    bi_res = client.post(
        "/api/insurance/claims",
        headers=headers,
        json={
            "claim_number": "CLM-BI-2026-901",
            "policy_id": policy.id,
            "claimant_name": "David Martinez",
            "loss_type": "bodily_injury",
            "estimated_loss": 800.00,
            "notes": "Slip and fall in warehouse corridor.",
        },
    )
    assert bi_res.status_code == 200, bi_res.text
    bi_data = bi_res.json()
    assert bi_data["auto_approved"] is False
    assert bi_data["status"] == "under_review"

    # 2. Large Commercial Property Loss ($250,000)
    comm_res = client.post(
        "/api/insurance/claims",
        headers=headers,
        json={
            "claim_number": "CLM-FIRE-2026-902",
            "policy_id": policy.id,
            "claimant_name": "Metropolis Warehouse LLC",
            "loss_type": "fire",
            "estimated_loss": 250000.00,
            "notes": "Electrical fire in sector B loading dock.",
        },
    )
    assert comm_res.status_code == 200, comm_res.text
    comm_data = comm_res.json()
    assert comm_data["auto_approved"] is False
    assert comm_data["status"] == "under_review"


def test_claims_idp_parsing(client, admin_user):
    """Test Intelligent Document Processing extraction from Police Reports, Medical Billing & Estimates."""
    from tests.conftest import _auth, _login

    headers = _auth(_login(client, "admin", "admin123"))

    # 1. Police Crash Report
    police_text = """
    CALIFORNIA HIGHWAY PATROL - COLLISION REPORT
    Report Number: CHP-2026-99120
    Investigating Officer: Sgt. Marcus Brody
    Badge #: 4412
    Date of Crash: 2026-05-12
    Location: Highway 101 Northbound Mile 42
    Cause of Crash: Driver 2 failure to yield right of way
    Citations: Section 21801 Failure to Yield Left Turn
    """
    pol_res = client.post(
        "/api/insurance/idp/extract",
        headers=headers,
        json={"doc_type": "police_report", "text": police_text},
    )
    assert pol_res.status_code == 200, pol_res.text
    pol_data = pol_res.json()
    assert pol_data["report_number"] == "CHP-2026-99120"
    assert pol_data["officer_name"] == "Sgt. Marcus Brody"
    assert "failure to yield" in pol_data["fault_determination"].lower()
    assert len(pol_data["citations"]) >= 1

    # 2. Medical Billing Record
    med_text = """
    CEDARS-SINAI MEDICAL CENTER
    Patient: James Holden
    Date of Service: 2026-05-14
    Diagnosis ICD-10: S06.0X0A (Concussion), M54.5 (Low Back Pain)
    Emergency Evaluation & CT Scan
    Total Charges: $4,850.00
    """
    med_res = client.post(
        "/api/insurance/idp/extract",
        headers=headers,
        json={"doc_type": "medical_record", "text": med_text},
    )
    assert med_res.status_code == 200, med_res.text
    med_data = med_res.json()
    assert med_data["patient_name"] == "James Holden"
    assert "S06.0X0A" in med_data["icd_codes"]
    assert med_data["total_billed"] == 4850.00

    # 3. Vehicle Repair Estimate
    rep_text = """
    CALIBER COLLISION CENTER
    Vehicle VIN: 1HGCR2F83HA123456
    2023 Honda Accord Sedan
    Parts Total: $2,400.00
    Labor Total: $1,600.00
    Total Hours: 32.5
    Grand Total: $4,000.00
    """
    rep_res = client.post(
        "/api/insurance/idp/extract",
        headers=headers,
        json={"doc_type": "repair_estimate", "text": rep_text},
    )
    assert rep_res.status_code == 200, rep_res.text
    rep_data = rep_res.json()
    assert rep_data["vin"] == "1HGCR2F83HA123456"
    assert rep_data["parts_total"] == 2400.00
    assert rep_data["labor_total"] == 1600.00
    assert rep_data["total_estimate"] == 4000.00


def test_fraud_detection_exif_and_duplicate_photo(client, admin_user, db_session, root_folder_id):
    """Test multi-format evidence upload, EXIF fraud evaluation, and cross-claim duplicate photo detection."""
    from tests.conftest import _auth, _login

    headers = _auth(_login(client, "admin", "admin123"))

    # Seed 2 separate claims
    policy = InsurancePolicy(
        policy_number="POL-AUTO-FRAUD-01",
        insured_name="Victor Stone",
        policy_type="auto",
        created_by=admin_user.id,
    )
    db_session.add(policy)
    db_session.commit()
    db_session.refresh(policy)

    claim1 = InsuranceClaim(
        claim_number="CLM-ORIG-101",
        policy_id=policy.id,
        claimant_name="Victor Stone",
        loss_type="collision",
        created_by=admin_user.id,
    )
    claim2 = InsuranceClaim(
        claim_number="CLM-SUSP-102",
        policy_id=policy.id,
        claimant_name="Arthur Curry",
        loss_type="collision",
        created_by=admin_user.id,
    )
    db_session.add_all([claim1, claim2])
    db_session.commit()
    db_session.refresh(claim1)
    db_session.refresh(claim2)

    # Generate synthetic crash photo JPEG bytes
    img = Image.new("RGB", (200, 200), color=(180, 40, 40))
    buf = io.BytesIO()
    img.save(buf, format="JPEG")
    photo_bytes = buf.getvalue()

    # 1. Upload photo to Claim 1
    ev1_res = client.post(
        f"/api/insurance/claims/{claim1.id}/evidence",
        headers=headers,
        data={"evidence_type": "scene_photo", "folder_id": root_folder_id, "notes": "Crash scene front bumper"},
        files={"file": ("crash_front.jpg", photo_bytes, "image/jpeg")},
    )
    assert ev1_res.status_code == 200, ev1_res.text
    ev1_data = ev1_res.json()
    assert ev1_data["image_hash"] is not None
    assert ev1_data["is_fraud_flagged"] is False

    # 2. Upload the EXACT SAME crash photo to Claim 2 (Cross-claim duplicate collision!)
    ev2_res = client.post(
        f"/api/insurance/claims/{claim2.id}/evidence",
        headers=headers,
        data={"evidence_type": "scene_photo", "folder_id": root_folder_id, "notes": "Damage photo"},
        files={"file": ("crash_front_duplicate.jpg", photo_bytes, "image/jpeg")},
    )
    assert ev2_res.status_code == 200, ev2_res.text
    ev2_data = ev2_res.json()
    assert ev2_data["is_fraud_flagged"] is True

    # Verify claim 2 fraud score incremented
    db_session.refresh(claim2)
    assert claim2.fraud_score >= 60
    assert any("Duplicate image" in f for f in (claim2.fraud_flags or []))


def test_settlement_statement_pdf_generation(client, admin_user, db_session):
    """Test generating official insurance claim settlement payout explanation PDF."""
    from tests.conftest import _auth, _login

    headers = _auth(_login(client, "admin", "admin123"))

    policy = InsurancePolicy(
        policy_number="POL-AUTO-PDF-01",
        insured_name="Bruce Wayne",
        policy_type="auto",
        deductible=1000.00,
        coverage_limit=1000000.00,
        created_by=admin_user.id,
    )
    db_session.add(policy)
    db_session.commit()
    db_session.refresh(policy)

    claim = InsuranceClaim(
        claim_number="CLM-PDF-9999",
        policy_id=policy.id,
        claimant_name="Bruce Wayne",
        loss_type="collision",
        estimated_loss=15000.00,
        settlement_amount=14000.00,
        status="approved",
        notes="Batmobile collision repairs approved at Gotham Bodyworks.",
        created_by=admin_user.id,
    )
    db_session.add(claim)
    db_session.commit()
    db_session.refresh(claim)

    res = client.post(
        f"/api/insurance/claims/{claim.id}/generate-settlement",
        headers=headers,
        json={"notes": "Final payout authorized by senior claims manager."},
    )
    assert res.status_code == 200, res.text
    assert res.headers["content-type"] == "application/pdf"
    assert len(res.content) > 1000
    assert res.content.startswith(b"%PDF")


def test_external_claim_portal_access(client, admin_user, db_session):
    """Test tokenized external portal for independent adjusters and policyholders."""
    from tests.conftest import _auth, _login

    headers = _auth(_login(client, "admin", "admin123"))

    policy = InsurancePolicy(
        policy_number="POL-PORTAL-01",
        insured_name="Barry Allen",
        policy_type="auto",
        created_by=admin_user.id,
    )
    db_session.add(policy)
    db_session.commit()
    db_session.refresh(policy)

    claim = InsuranceClaim(
        claim_number="CLM-PORTAL-007",
        policy_id=policy.id,
        claimant_name="Barry Allen",
        loss_type="collision",
        created_by=admin_user.id,
    )
    db_session.add(claim)
    db_session.commit()
    db_session.refresh(claim)

    # 1. Create Portal
    p_res = client.post(
        "/api/insurance/portals",
        headers=headers,
        json={
            "claim_id": claim.id,
            "recipient_email": "adjuster.smith@crawfordco.com",
            "recipient_name": "TPA Senior Adjuster",
            "recipient_role": "independent_adjuster",
            "password": "AdjusterSecretPassword!2026",
            "expires_in_days": 14,
        },
    )
    assert p_res.status_code == 200, p_res.text
    p_data = p_res.json()
    token = p_data["token"]
    assert len(token) > 10

    # 2. Access Portal with Password
    acc_res = client.post(
        f"/api/insurance/portals/{token}/access",
        json={"password": "AdjusterSecretPassword!2026"},
    )
    assert acc_res.status_code == 200, acc_res.text
    acc_data = acc_res.json()
    assert acc_data["status"] == "authorized"
    assert acc_data["claim_number"] == "CLM-PORTAL-007"
    assert acc_data["recipient_role"] == "independent_adjuster"
