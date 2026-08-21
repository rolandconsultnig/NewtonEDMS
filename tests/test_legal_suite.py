"""Test suite for Legal Practice Management & Corporate Legal Department EDMS Suite."""
from __future__ import annotations

import io
import pytest
from fastapi.testclient import TestClient

from app.security import get_password_hash
from app.bates import stamp_bates_pdf
from app.database import now
from app.legal_compare import compute_legal_redline
from app.legal_matter_engine import is_user_walled
from app.models import Document, EthicalWall, LegalTemplate, Matter, MatterDocument, User
from app.redaction import redact_text_stream


@pytest.fixture
def legal_users(db_session):
    """Create test attorneys and staff."""
    pw = get_password_hash("attorney123")
    attorney_a = User(username="attorney_smith", email="smith@lawfirm.com", role="user", hashed_password=pw)
    attorney_b = User(username="attorney_jones", email="jones@lawfirm.com", role="user", hashed_password=pw)
    paralegal = User(username="paralegal_clark", email="clark@lawfirm.com", role="user", hashed_password=pw)
    db_session.add_all([attorney_a, attorney_b, paralegal])
    db_session.commit()
    db_session.refresh(attorney_a)
    db_session.refresh(attorney_b)
    db_session.refresh(paralegal)
    return {"smith": attorney_a, "jones": attorney_b, "clark": paralegal}


def test_matter_centric_architecture(client, admin_user, root_folder_id, db_session):
    """Test creating a matter, updating details, and attaching pleadings & exhibits."""
    from tests.conftest import _auth, _login

    headers = _auth(_login(client, "admin", "admin123"))

    # 1. Create Matter
    res = client.post(
        "/api/legal/matters",
        headers=headers,
        json={
            "matter_number": "MAT-2026-001",
            "title": "In re Acme Corp Patent Infringement",
            "client_name": "Acme Corporation",
            "practice_area": "Intellectual Property",
            "court_name": "U.S. District Court, N.D. California",
            "case_caption": "Acme Corp. v. Global Tech Ltd.",
            "judge_name": "Hon. Sarah Jenkins",
            "billing_code": "ACM-IP-9901",
        },
    )
    assert res.status_code == 200, res.text
    matter_data = res.json()
    assert matter_data["matter_number"] == "MAT-2026-001"
    matter_id = matter_data["id"]

    # 2. Upload Document
    doc = Document(
        name="Complaint.pdf",
        title="Complaint for Patent Infringement",
        file_path="pleadings/complaint.pdf",
        folder_id=root_folder_id,
        created_by=admin_user.id,
        status="active",
    )
    db_session.add(doc)
    db_session.commit()
    db_session.refresh(doc)

    # 3. Attach to Matter as Pleading
    attach_res = client.post(
        f"/api/legal/matters/{matter_id}/documents",
        headers=headers,
        json={
            "document_id": doc.id,
            "category": "pleading",
            "confidentiality": "public",
            "pinned": True,
            "notes": "Filed initial complaint",
        },
    )
    assert attach_res.status_code == 200
    assert attach_res.json()["category"] == "pleading"

    # 4. Query Matter Documents
    docs_res = client.get(f"/api/legal/matters/{matter_id}/documents", headers=headers)
    assert docs_res.status_code == 200
    docs_list = docs_res.json()
    assert len(docs_list) == 1
    assert docs_list[0]["category"] == "pleading"
    assert docs_list[0]["title"] == "Complaint for Patent Infringement"


def test_ethical_wall_conflict_enforcement(client, admin_user, legal_users, db_session):
    """Test ethical walls preventing conflicted attorneys from accessing adverse client matters."""
    from tests.conftest import _auth, _login

    headers_admin = _auth(_login(client, "admin", "admin123"))
    headers_smith = _auth(_login(client, legal_users["smith"].username, "attorney123"))
    headers_jones = _auth(_login(client, legal_users["jones"].username, "attorney123"))

    # 1. Admin creates matter
    m_res = client.post(
        "/api/legal/matters",
        headers=headers_admin,
        json={
            "matter_number": "MAT-WALL-002",
            "title": "Adverse Acquisition Defense",
            "client_name": "MegaCorp Industries",
            "practice_area": "Corporate / M&A",
        },
    )
    matter_id = m_res.json()["id"]

    # 2. Erect Ethical Wall blocking Attorney Jones (prior representation conflict)
    wall_res = client.post(
        "/api/legal/walls",
        headers=headers_admin,
        json={
            "matter_id": matter_id,
            "walled_user_ids": [legal_users["jones"].id],
            "reason": "Prior representation of MegaCorp target entity at former firm.",
        },
    )
    assert wall_res.status_code == 200

    # 3. Attorney Smith (Allowed) accesses Matter
    smith_res = client.get(f"/api/legal/matters/{matter_id}", headers=headers_smith)
    assert smith_res.status_code == 200

    # 4. Attorney Jones (Walled) attempts to access Matter -> 403 Forbidden!
    jones_res = client.get(f"/api/legal/matters/{matter_id}", headers=headers_jones)
    assert jones_res.status_code == 403
    assert "Ethical Wall" in jones_res.json()["detail"]

    # 5. Filtered list: Attorney Jones does not see the walled matter in portfolio
    jones_list = client.get("/api/legal/matters", headers=headers_jones).json()
    assert not any(m["id"] == matter_id for m in jones_list)


def test_deep_email_filing(client, admin_user, db_session):
    """Test parsing .eml message with headers and attachments and filing to Matter."""
    from tests.conftest import _auth, _login

    headers = _auth(_login(client, "admin", "admin123"))

    matter = Matter(
        matter_number="MAT-EMAIL-003",
        title="Contract Dispute",
        client_name="Delta Services",
        created_by=admin_user.id,
    )
    db_session.add(matter)
    db_session.commit()
    db_session.refresh(matter)

    # Construct sample RFC 822 .eml with attachment
    raw_eml = (
        b"From: opposing.counsel@lexfirm.com\r\n"
        b"To: admin@newtonedms.local\r\n"
        b"Cc: associate@lexfirm.com\r\n"
        b"Subject: Settlement Offer - Delta Dispute\r\n"
        b"Date: Wed, 20 Aug 2026 14:00:00 -0400\r\n"
        b"Message-ID: <msg-998811@lexfirm.com>\r\n"
        b"MIME-Version: 1.0\r\n"
        b"Content-Type: multipart/mixed; boundary=\"BOUNDARY123\"\r\n"
        b"\r\n"
        b"--BOUNDARY123\r\n"
        b"Content-Type: text/plain; charset=utf-8\r\n"
        b"\r\n"
        b"Please find attached our client's formal settlement proposal.\r\n"
        b"\r\n"
        b"--BOUNDARY123\r\n"
        b"Content-Type: application/pdf\r\n"
        b"Content-Disposition: attachment; filename=\"Settlement_Proposal.pdf\"\r\n"
        b"\r\n"
        b"%PDF-1.4 Mock Settlement Proposal Content\r\n"
        b"--BOUNDARY123--\r\n"
    )

    files = {"file": ("settlement.eml", io.BytesIO(raw_eml), "message/rfc822")}
    res = client.post(
        f"/api/legal/matters/{matter.id}/emails/ingest",
        headers=headers,
        files=files,
    )
    assert res.status_code == 200, res.text
    data = res.json()
    assert data["subject"] == "Settlement Offer - Delta Dispute"
    assert data["from"] == "opposing.counsel@lexfirm.com"
    assert data["attachment_count"] == 1
    assert data["attachments"][0]["title"] == "Settlement_Proposal.pdf"


def test_automated_document_assembly(client, admin_user, db_session):
    """Test generating a legal instrument from master template with matter variable substitution."""
    from tests.conftest import _auth, _login

    headers = _auth(_login(client, "admin", "admin123"))

    # Fetch templates
    tpls_res = client.get("/api/legal/templates", headers=headers)
    assert tpls_res.status_code == 200
    tpls = tpls_res.json()
    assert len(tpls) >= 1
    nda_tpl = next(t for t in tpls if "Non-Disclosure" in t["name"])

    matter = Matter(
        matter_number="MAT-NDA-004",
        title="Joint Venture Talks",
        client_name="Apex BioTech",
        created_by=admin_user.id,
    )
    db_session.add(matter)
    db_session.commit()
    db_session.refresh(matter)

    # Assemble NDA
    asm_res = client.post(
        "/api/legal/assembly/generate",
        headers=headers,
        json={
            "template_id": nda_tpl["id"],
            "matter_id": matter.id,
            "variables": {
                "counterparty_name": "Vertex Pharma Corp",
                "purpose": "Evaluating potential oncology research collaboration",
                "governing_jurisdiction": "State of Delaware",
                "client_signatory_name": "Dr. Eleanor Vance",
                "client_signatory_title": "Chief Executive Officer",
            },
            "output_format": "pdf",
        },
    )
    assert asm_res.status_code == 200, asm_res.text
    data = asm_res.json()
    assert data["status"] == "success"
    assert "Apex BioTech" in data["rendered_preview"]
    assert "Vertex Pharma Corp" in data["rendered_preview"]


def test_bates_stamping_and_discovery_production(client, admin_user, db_session, root_folder_id):
    """Test Bates stamping sequential numbers (PLTF-000001) across discovery PDFs."""
    from tests.conftest import _auth, _login

    headers = _auth(_login(client, "admin", "admin123"))

    matter = Matter(
        matter_number="MAT-BATES-005",
        title="Antitrust Investigation",
        client_name="Stark Industries",
        created_by=admin_user.id,
    )
    db_session.add(matter)
    db_session.commit()
    db_session.refresh(matter)

    doc1 = Document(
        name="EmailRecords.pdf",
        title="Email Records 2025",
        file_path="discovery/emails.pdf",
        folder_id=root_folder_id,
        created_by=admin_user.id,
        status="active",
    )
    doc2 = Document(
        name="FinancialLedger.pdf",
        title="Financial Ledger Q4",
        file_path="discovery/ledger.pdf",
        folder_id=root_folder_id,
        created_by=admin_user.id,
        status="active",
    )
    db_session.add_all([doc1, doc2])
    db_session.commit()
    db_session.refresh(doc1)
    db_session.refresh(doc2)

    # Execute Bates Stamping Run
    bates_res = client.post(
        "/api/legal/bates/apply",
        headers=headers,
        json={
            "matter_id": matter.id,
            "document_ids": [doc1.id, doc2.id],
            "production_set": "VOL-001",
            "prefix": "STARK",
            "start_number": 100,
            "pad_length": 6,
            "position": "bottom-right",
            "disclaimer_text": "CONFIDENTIAL - ATTORNEYS' EYES ONLY",
        },
    )
    assert bates_res.status_code == 200, bates_res.text
    data = bates_res.json()
    assert data["status"] == "success"
    assert data["bates_start"] == "STARK-000100"
    assert data["total_documents"] == 2
    assert len(data["items"]) == 2


def test_permanent_non_reversible_redaction(client, admin_user, db_session, root_folder_id):
    """Test permanent redaction removing SSN and PII text permanently."""
    from tests.conftest import _auth, _login

    headers = _auth(_login(client, "admin", "admin123"))

    doc = Document(
        name="EmployeeRecord.txt",
        title="Employee Personnel File",
        file_path="personnel/emp1.txt",
        extracted_text="Employee John Doe, SSN: 123-45-6789, Credit Card: 4532-1100-2200-3300, salary $150,000.",
        folder_id=root_folder_id,
        created_by=admin_user.id,
        status="active",
    )
    db_session.add(doc)
    db_session.commit()
    db_session.refresh(doc)

    # Apply Permanent Redaction
    red_res = client.post(
        f"/api/legal/documents/{doc.id}/redact-permanent",
        headers=headers,
        json={
            "builtin_presets": ["us_ssn", "credit_card"],
            "save_as_new": True,
        },
    )
    assert red_res.status_code == 200, red_res.text
    data = red_res.json()
    assert data["status"] == "success"
    assert data["redactions_applied"] >= 2

    # Verify redacted copy
    red_doc = db_session.get(Document, data["redacted_document_id"])
    assert "123-45-6789" not in red_doc.extracted_text
    assert "4532-1100-2200-3300" not in red_doc.extracted_text
    assert "██████████" in red_doc.extracted_text


def test_legal_redline_comparison(client, admin_user, db_session, root_folder_id):
    """Test legal redlining highlighting additions and deletions between versions."""
    from tests.conftest import _auth, _login

    headers = _auth(_login(client, "admin", "admin123"))

    doc_orig = Document(
        name="Contract_v1.txt",
        title="Master Services Agreement v1",
        file_path="contracts/v1.txt",
        extracted_text="The supplier shall deliver goods within 30 business days. Total payment is $50,000.",
        folder_id=root_folder_id,
        created_by=admin_user.id,
        status="active",
    )
    doc_revised = Document(
        name="Contract_v2.txt",
        title="Master Services Agreement v2",
        file_path="contracts/v2.txt",
        extracted_text="The vendor shall deliver goods within 14 calendar days. Total payment is $75,000 net 30.",
        folder_id=root_folder_id,
        created_by=admin_user.id,
        status="active",
    )
    db_session.add_all([doc_orig, doc_revised])
    db_session.commit()
    db_session.refresh(doc_orig)
    db_session.refresh(doc_revised)

    # Compare
    cmp_res = client.post(
        "/api/legal/compare",
        headers=headers,
        json={
            "doc_id_a": doc_orig.id,
            "doc_id_b": doc_revised.id,
        },
    )
    assert cmp_res.status_code == 200, cmp_res.text
    data = cmp_res.json()
    assert data["status"] == "success"
    assert data["insertions_count"] > 0
    assert data["deletions_count"] > 0
    assert "<del" in data["inline_html"]
    assert "<ins" in data["inline_html"]


def test_court_efiling_packaging(client, admin_user, db_session, root_folder_id):
    """Test court-compliant e-Filing package bundling with Caption Cover Sheet & SHA-256 cert."""
    from tests.conftest import _auth, _login

    headers = _auth(_login(client, "admin", "admin123"))

    matter = Matter(
        matter_number="MAT-EFILING-007",
        title="Commercial Arbitration",
        client_name="Global Logistics Corp",
        court_name="U.S. District Court, S.D.N.Y.",
        case_caption="Global Logistics Corp. v. Harbor Freight Co.",
        created_by=admin_user.id,
    )
    db_session.add(matter)
    db_session.commit()
    db_session.refresh(matter)

    pleading = Document(
        name="MotionToDismiss.pdf",
        title="Motion to Dismiss Under Rule 12(b)(6)",
        file_path="pleadings/motion.pdf",
        folder_id=root_folder_id,
        created_by=admin_user.id,
        status="active",
    )
    exhibit_a = Document(
        name="ExhibitA_Contract.pdf",
        title="Executed Master Agreement",
        file_path="exhibits/ex_a.pdf",
        folder_id=root_folder_id,
        created_by=admin_user.id,
        status="active",
    )
    db_session.add_all([pleading, exhibit_a])
    db_session.commit()
    db_session.refresh(pleading)
    db_session.refresh(exhibit_a)

    # Package e-Filing Bundle
    efile_res = client.post(
        f"/api/legal/matters/{matter.id}/efiling/package",
        headers=headers,
        json={
            "matter_id": matter.id,
            "pleading_doc_id": pleading.id,
            "exhibit_doc_ids": [exhibit_a.id],
            "package_name": "E-Filing Package - Motion to Dismiss",
        },
    )
    assert efile_res.status_code == 200, efile_res.text
    data = efile_res.json()
    assert data["status"] == "success"
    assert len(data["efiling_hash"]) == 64  # Valid SHA-256
    assert data["exhibit_count"] == 1
    assert data["exhibits"][0]["letter"] == "A"


def test_secure_client_extranet_portal(client, admin_user, db_session, root_folder_id):
    """Test secure client extranet portal with encrypted token, password protection, and access audit."""
    from tests.conftest import _auth, _login

    headers = _auth(_login(client, "admin", "admin123"))

    matter = Matter(
        matter_number="MAT-PORTAL-008",
        title="Estate Planning Matter",
        client_name="Robert Vance",
        created_by=admin_user.id,
    )
    doc = Document(
        name="Will_and_Trust.pdf",
        title="Last Will and Testament",
        file_path="estate/will.pdf",
        folder_id=root_folder_id,
        created_by=admin_user.id,
        status="active",
    )
    db_session.add_all([matter, doc])
    db_session.commit()
    db_session.refresh(matter)
    db_session.refresh(doc)

    # 1. Create Portal Share
    portal_res = client.post(
        "/api/legal/portals",
        headers=headers,
        json={
            "matter_id": matter.id,
            "document_ids": [doc.id],
            "recipient_email": "client.vance@example.com",
            "recipient_name": "Robert Vance",
            "password": "ClientSecurePass!2026",
            "watermark_text": "CONFIDENTIAL ESTATE DOCUMENT",
            "expires_in_days": 14,
        },
    )
    assert portal_res.status_code == 200, portal_res.text
    portal_token = portal_res.json()["token"]

    # 2. Access with wrong/missing password -> 401 Unauthorized
    bad_res = client.get(f"/api/legal/portals/{portal_token}")
    assert bad_res.status_code == 401

    # 3. Access with correct password -> 200 Authorized
    good_res = client.get(f"/api/legal/portals/{portal_token}?password=ClientSecurePass!2026")
    assert good_res.status_code == 200
    portal_data = good_res.json()
    assert portal_data["status"] == "authorized"
    assert portal_data["client_name"] == "Robert Vance"
    assert len(portal_data["documents"]) == 1
    assert portal_data["documents"][0]["title"] == "Last Will and Testament"
