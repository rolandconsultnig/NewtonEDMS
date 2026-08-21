"""Automated Test Suite for Accounting & Financial EDMS Features.

Validates:
1. 2-Way and 3-Way Matching (POs, GRNs, line items, price/quantity variances)
2. Intelligent Invoice OCR & Line-Item Data Extraction
3. ERP & General Ledger (GL) Synchronization
4. PEPPOL BIS Billing 3.0 / UBL XML E-Invoicing Validation
5. Duplicate Invoice Detection
6. Batch Barcode & Separator Sheet Splitting
7. Read-Only Auditor Review Portals
"""
from __future__ import annotations

import io
from datetime import datetime, timedelta
import pytest
from fastapi.testclient import TestClient
from fpdf import FPDF

from app.database import now
from app.models import Document, GoodsReceivedNote, InvoiceRecord, PurchaseOrder, User
from app.security import get_password_hash


@pytest.fixture()
def ap_users(db_session):
    ap_clerk = User(
        username="ap_clerk",
        email="ap@example.com",
        hashed_password=get_password_hash("ap12345"),
        role="user",
        is_active=True,
    )
    controller = User(
        username="controller",
        email="controller@example.com",
        hashed_password=get_password_hash("controller123"),
        role="finance",
        is_active=True,
    )
    db_session.add_all([ap_clerk, controller])
    db_session.commit()
    db_session.refresh(ap_clerk)
    db_session.refresh(controller)
    return {"clerk": ap_clerk, "controller": controller}


def test_po_and_grn_creation(client, admin_user, db_session):
    """Test registering Purchase Orders and Goods Received Notes with line item specs."""
    from tests.conftest import _auth, _login

    headers = _auth(_login(client, "admin", "admin123"))

    # 1. Create PO
    po_res = client.post(
        "/api/accounting/purchase-orders",
        headers=headers,
        json={
            "po_number": "PO-2026-9001",
            "vendor_name": "Dell Technologies",
            "total_amount": 5000.00,
            "currency": "USD",
            "line_items": [
                {"item_code": "LAPTOP-01", "description": "Dell XPS 15", "qty": 2, "unit_price": 2000.0, "total": 4000.0},
                {"item_code": "MONITOR-01", "description": "Dell 27 4K Monitor", "qty": 2, "unit_price": 500.0, "total": 1000.0},
            ],
        },
    )
    assert po_res.status_code == 200, po_res.text
    po_data = po_res.json()
    assert po_data["po_number"] == "PO-2026-9001"
    assert len(po_data["line_items"]) == 2

    # 2. Create GRN (Warehouse receipt)
    grn_res = client.post(
        "/api/accounting/grns",
        headers=headers,
        json={
            "grn_number": "GRN-2026-4401",
            "po_number": "PO-2026-9001",
            "vendor_name": "Dell Technologies",
            "line_items": [
                {"item_code": "LAPTOP-01", "description": "Dell XPS 15", "received_qty": 2, "accepted_qty": 2},
                {"item_code": "MONITOR-01", "description": "Dell 27 4K Monitor", "received_qty": 2, "accepted_qty": 2},
            ],
        },
    )
    assert grn_res.status_code == 200, grn_res.text
    grn_data = grn_res.json()
    assert grn_data["grn_number"] == "GRN-2026-4401"
    assert grn_data["po_number"] == "PO-2026-9001"


def test_automated_3way_matching(client, admin_user, db_session):
    """Test 3-Way matching between Invoice, Purchase Order, and Goods Received Note."""
    from tests.conftest import _auth, _login

    headers = _auth(_login(client, "admin", "admin123"))

    # Seed PO and GRN
    po = PurchaseOrder(
        po_number="PO-MATCH-001",
        vendor_name="Acme Industrial",
        total_amount=1200.00,
        status="issued",
        line_items=[{"item_code": "WIDGET-A", "description": "Standard Widget", "qty": 10, "unit_price": 120.0, "total": 1200.0}],
        created_by=admin_user.id,
    )
    grn = GoodsReceivedNote(
        grn_number="GRN-MATCH-001",
        po_number="PO-MATCH-001",
        vendor_name="Acme Industrial",
        line_items=[{"item_code": "WIDGET-A", "description": "Standard Widget", "received_qty": 10, "accepted_qty": 10}],
        created_by=admin_user.id,
    )
    db_session.add_all([po, grn])
    db_session.commit()

    # 1. Exact Match Invoice (Matches 3-Way)
    inv_res = client.post(
        "/api/accounting/invoices",
        headers=headers,
        json={
            "invoice_number": "INV-ACME-8801",
            "vendor_name": "Acme Industrial",
            "vendor_tax_id": "US-99887766",
            "po_number": "PO-MATCH-001",
            "grn_number": "GRN-MATCH-001",
            "total_amount": 1200.00,
            "line_items": [{"item_code": "WIDGET-A", "description": "Standard Widget", "qty": 10, "unit_price": 120.0, "total": 1200.0}],
        },
    )
    assert inv_res.status_code == 200, inv_res.text
    inv_data = inv_res.json()
    assert inv_data["matching_status"] == "matched_3way"

    # 2. Quantity Variance Discrepancy (Invoiced 15, but warehouse only received 10)
    var_res = client.post(
        "/api/accounting/invoices",
        headers=headers,
        json={
            "invoice_number": "INV-ACME-8802",
            "vendor_name": "Acme Industrial",
            "vendor_tax_id": "US-99887766",
            "po_number": "PO-MATCH-001",
            "grn_number": "GRN-MATCH-001",
            "total_amount": 1800.00,
            "line_items": [{"item_code": "WIDGET-A", "description": "Standard Widget", "qty": 15, "unit_price": 120.0, "total": 1800.0}],
        },
    )
    assert var_res.status_code == 200
    var_data = var_res.json()
    assert var_data["matching_status"] in ("price_variance", "quantity_variance", "discrepancy")


def test_intelligent_ocr_and_line_item_extraction(client, admin_user):
    """Test extracting structured invoice fields and line items from OCR text."""
    from tests.conftest import _auth, _login

    headers = _auth(_login(client, "admin", "admin123"))

    raw_ocr = """
    GLOBAL SUPPLY CORP
    100 Industrial Parkway, Austin TX
    Tax ID: US-45892019

    INVOICE # INV-2026-7788
    PO Number: PO-992200
    Invoice Date: 2026-04-15
    Due Date: 2026-05-15

    Description Qty Unit Price Total
    High-Speed Router 2 250.00 500.00
    Ethernet Cable 100ft 5 20.00 100.00

    Subtotal: $600.00
    Sales Tax: $48.00
    Total Amount: $648.00
    """

    res = client.post(
        "/api/accounting/invoices/extract-ocr",
        headers=headers,
        json={"text": raw_ocr},
    )
    assert res.status_code == 200, res.text
    data = res.json()

    assert data["invoice_number"] == "INV-2026-7788"
    assert data["vendor_tax_id"] == "US-45892019"
    assert data["po_number"] == "PO-992200"
    assert data["total_amount"] == 648.00
    assert data["subtotal"] == 600.00
    assert data["tax_amount"] == 48.00
    assert len(data["line_items"]) == 2
    assert data["line_items"][0]["description"] == "High-Speed Router"
    assert data["line_items"][0]["qty"] == 2.0


def test_duplicate_invoice_detection(client, admin_user, db_session):
    """Test multi-factor duplicate invoice detection preventing fraudulent double-billing."""
    from tests.conftest import _auth, _login

    headers = _auth(_login(client, "admin", "admin123"))

    # Seed original invoice
    orig_inv = InvoiceRecord(
        invoice_number="INV-DUP-100",
        vendor_name="Apex Logistics LLC",
        vendor_tax_id="VAT-99001122",
        total_amount=3500.00,
        invoice_date=now(),
        created_by=admin_user.id,
    )
    db_session.add(orig_inv)
    db_session.commit()

    # Check duplicate with same tax ID and invoice number
    dup_res = client.post(
        "/api/accounting/invoices/check-duplicate",
        headers=headers,
        json={
            "vendor_name": "Apex Logistics LLC",
            "vendor_tax_id": "VAT-99001122",
            "invoice_number": "INV-DUP-100",
            "total_amount": 3500.00,
        },
    )
    assert dup_res.status_code == 200, dup_res.text
    data = dup_res.json()
    assert data["is_duplicate"] is True
    assert data["confidence"] >= 90
    assert data["duplicate_of_id"] == orig_inv.id


def test_peppol_einvoicing_validation(client, admin_user):
    """Test validation of PEPPOL BIS Billing 3.0 XML e-Invoices."""
    from tests.conftest import _auth, _login

    headers = _auth(_login(client, "admin", "admin123"))

    sample_peppol_xml = """<?xml version="1.0" encoding="UTF-8"?>
    <Invoice xmlns="urn:oasis:names:specification:ubl:schema:xsd:Invoice-2"
             xmlns:cac="urn:oasis:names:specification:ubl:schema:xsd:CommonAggregateComponents-2"
             xmlns:cbc="urn:oasis:names:specification:ubl:schema:xsd:CommonBasicComponents-2">
        <cbc:CustomizationID>urn:cen.eu:en16931:2017#compliant#urn:fdc:peppol.eu:2017:poacc:billing:3.0</cbc:CustomizationID>
        <cbc:ID>PEPPOL-INV-2026-001</cbc:ID>
        <cbc:IssueDate>2026-06-01</cbc:IssueDate>
        <cbc:DueDate>2026-07-01</cbc:DueDate>
        <cbc:DocumentCurrencyCode>EUR</cbc:DocumentCurrencyCode>
        <cac:AccountingSupplierParty>
            <cac:Party>
                <cac:PartyName><cbc:Name>Nordic Cloud Solutions AS</cbc:Name></cac:PartyName>
                <cac:PartyTaxScheme><cbc:CompanyID>NO987654321MVA</cbc:CompanyID></cac:PartyTaxScheme>
            </cac:Party>
        </cac:AccountingSupplierParty>
        <cac:AccountingCustomerParty>
            <cac:Party>
                <cac:PartyName><cbc:Name>Enterprise Buyer AB</cbc:Name></cac:PartyName>
            </cac:Party>
        </cac:AccountingCustomerParty>
        <cac:LegalMonetaryTotal>
            <cbc:LineExtensionAmount>1000.00</cbc:LineExtensionAmount>
            <cbc:TaxExclusiveAmount>1000.00</cbc:TaxExclusiveAmount>
            <cbc:TaxInclusiveAmount>1250.00</cbc:TaxInclusiveAmount>
            <cbc:PayableAmount>1250.00</cbc:PayableAmount>
        </cac:LegalMonetaryTotal>
        <cac:InvoiceLine>
            <cbc:ID>1</cbc:ID>
            <cbc:InvoicedQuantity>1</cbc:InvoicedQuantity>
            <cac:Item><cbc:Name>Cloud Hosting Subscription</cbc:Name></cac:Item>
            <cac:Price><cbc:PriceAmount>1000.00</cbc:PriceAmount></cac:Price>
        </cac:InvoiceLine>
    </Invoice>"""

    res = client.post(
        "/api/accounting/einvoice/validate",
        headers=headers,
        files={"file": ("invoice_peppol.xml", sample_peppol_xml.encode("utf-8"), "application/xml")},
    )
    assert res.status_code == 200, res.text
    data = res.json()
    assert data["valid"] is True
    assert data["standard"] == "PEPPOL BIS Billing 3.0"
    assert data["invoice_number"] == "PEPPOL-INV-2026-001"
    assert data["supplier_name"] == "Nordic Cloud Solutions AS"
    assert data["payable_amount"] == 1250.00
    assert data["line_items_count"] == 1


def test_batch_document_barcode_splitting(client, admin_user, root_folder_id):
    """Test splitting multi-page scanned PDF batches using barcode separator pages."""
    from tests.conftest import _auth, _login

    headers = _auth(_login(client, "admin", "admin123"))

    # Generate 3-page synthetic PDF with barcode separator on page 2
    pdf = FPDF()
    pdf.add_page()
    pdf.set_font("Helvetica", size=12)
    pdf.cell(0, 10, "INVOICE VOUCHER 1 - Page 1")

    pdf.add_page()
    pdf.cell(0, 10, "BARCODE:SEP-INV-BATCH-002 [PAGE_SPLIT]")

    pdf.add_page()
    pdf.cell(0, 10, "INVOICE VOUCHER 2 - Page 2")

    batch_pdf_bytes = bytes(pdf.output())

    res = client.post(
        "/api/accounting/batch-split",
        headers=headers,
        data={"folder_id": root_folder_id, "batch_name": "AP_Scans_April"},
        files={"file": ("batch_scan.pdf", batch_pdf_bytes, "application/pdf")},
    )
    assert res.status_code == 200, res.text
    data = res.json()
    assert data["status"] == "success"
    assert data["split_documents_count"] >= 1


def test_erp_gl_synchronization(client, admin_user, db_session, root_folder_id):
    """Test syncing approved invoices to ERP systems (SAP, NetSuite, QuickBooks) with GL account mapping."""
    from tests.conftest import _auth, _login

    headers = _auth(_login(client, "admin", "admin123"))

    doc = Document(
        name="VendorInvoice_SAP.pdf",
        title="Office Equipment Invoice",
        file_path="accounting/invoices/sap_inv.pdf",
        folder_id=root_folder_id,
        created_by=admin_user.id,
        status="active",
    )
    inv = InvoiceRecord(
        invoice_number="INV-SAP-9901",
        vendor_name="Herman Miller Ergonomics",
        total_amount=4800.00,
        document_id=None,
        payment_status="approved",
        created_by=admin_user.id,
    )
    db_session.add_all([doc, inv])
    db_session.commit()
    db_session.refresh(doc)
    db_session.refresh(inv)
    inv.document_id = doc.id
    db_session.commit()

    # Sync to SAP
    sync_res = client.post(
        f"/api/accounting/invoices/{inv.id}/erp-sync",
        headers=headers,
        json={
            "platform": "sap",
            "gl_account": "6020-Office Furniture",
            "cost_center": "CC-FACILITIES-01",
        },
    )
    assert sync_res.status_code == 200, sync_res.text
    data = sync_res.json()
    assert data["status"] == "synced"
    assert data["platform"] == "sap"
    assert "SAP-VOUCHER-" in data["voucher_reference"]
    assert data["gl_account"] == "6020-Office Furniture"


def test_auditor_portal_access(client, admin_user, db_session, root_folder_id):
    """Test read-only auditor review portal with encrypted token, password protection, and access audit."""
    from tests.conftest import _auth, _login

    headers = _auth(_login(client, "admin", "admin123"))

    sample_doc = Document(
        name="Sample_Financial_Report.pdf",
        title="Q1 Audited Balance Sheet",
        file_path="accounting/audit/q1_balance.pdf",
        folder_id=root_folder_id,
        created_by=admin_user.id,
        status="active",
    )
    db_session.add(sample_doc)
    db_session.commit()
    db_session.refresh(sample_doc)

    # 1. Create Auditor Portal
    portal_res = client.post(
        "/api/accounting/auditor-portals",
        headers=headers,
        json={
            "auditor_name": "KPMG Audit Lead",
            "auditor_email": "auditor.lead@kpmg.com",
            "firm_name": "KPMG LLP",
            "sample_document_ids": [sample_doc.id],
            "allowed_gl_accounts": ["1000-Cash", "2000-AP", "6000-OpEx"],
            "password": "AuditorPassword!2026",
            "expires_in_days": 10,
        },
    )
    assert portal_res.status_code == 200, portal_res.text
    portal_data = portal_res.json()
    token = portal_data["token"]
    assert len(token) > 10

    # 2. Access portal with correct password
    acc_res = client.post(
        f"/api/accounting/auditor-portals/{token}/access",
        json={"password": "AuditorPassword!2026"},
    )
    assert acc_res.status_code == 200, acc_res.text
    acc_data = acc_res.json()
    assert acc_data["status"] == "authorized"
    assert acc_data["auditor_name"] == "KPMG Audit Lead"
    assert len(acc_data["sample_documents"]) == 1
    assert acc_data["sample_documents"][0]["title"] == "Q1 Audited Balance Sheet"

    # 3. Access portal with incorrect password fails
    bad_res = client.post(
        f"/api/accounting/auditor-portals/{token}/access",
        json={"password": "WrongPassword"},
    )
    assert bad_res.status_code == 401
