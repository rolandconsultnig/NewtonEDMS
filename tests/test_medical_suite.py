"""Automated Test Suite for Healthcare & Medical EDMS Suite.

Validates:
1. Patient Master Index (MPI) and Encounter Hierarchy
2. ABAC Sensitivity & Psychiatric Record Lockout
3. Emergency 'Break-Glass' Clinical Access Override
4. Bedside Barcode Ingestion & Wristband Matching
5. HL7 v2.x Message Parsing and FHIR DocumentReference Export
6. DICOM & PACS Medical Imaging Metadata
7. Bedside Digital Informed Consent & Cryptographic PDF Generation
8. Clinical IDP Extraction (Vitals, ICD-10 Diagnoses, Medications, Allergies)
"""
from __future__ import annotations

import io
from datetime import datetime, timedelta
import pytest
from fastapi.testclient import TestClient

from app.database import now
from app.models import Document, MedicalDocument, Patient, PatientEncounter, User
from app.security import get_password_hash


@pytest.fixture()
def medical_users(db_session):
    nurse = User(
        username="nurse_jackie",
        email="nurse@hospital.org",
        hashed_password=get_password_hash("nurse123"),
        role="user",
        is_active=True,
    )
    doctor = User(
        username="dr_house",
        email="house@hospital.org",
        hashed_password=get_password_hash("doctor123"),
        role="physician",
        is_active=True,
    )
    db_session.add_all([nurse, doctor])
    db_session.commit()
    db_session.refresh(nurse)
    db_session.refresh(doctor)
    return {"nurse": nurse, "doctor": doctor}


def test_patient_and_encounter_lifecycle(client, admin_user):
    """Test registering Master Patient Index and Admission Encounter."""
    from tests.conftest import _auth, _login

    headers = _auth(_login(client, "admin", "admin123"))

    # 1. Register Patient
    pat_res = client.post(
        "/api/medical/patients",
        headers=headers,
        json={
            "mrn": "MRN-2026-7788",
            "first_name": "Eleanor",
            "last_name": "Vance",
            "dob": "1988-04-12T00:00:00",
            "gender": "F",
            "blood_type": "O+",
            "primary_physician": "Dr. Allison Cameron",
            "insurance_id": "BCBS-99881122",
        },
    )
    assert pat_res.status_code == 200, pat_res.text
    pat_data = pat_res.json()
    assert pat_data["mrn"] == "MRN-2026-7788"
    patient_id = pat_data["id"]

    # 2. Register Encounter
    enc_res = client.post(
        "/api/medical/encounters",
        headers=headers,
        json={
            "encounter_number": "ENC-2026-9901",
            "patient_id": patient_id,
            "encounter_type": "inpatient",
            "department": "Cardiology",
            "attending_physician": "Dr. Robert Chase",
            "chief_complaint": "Acute chest pressure radiating to left arm",
        },
    )
    assert enc_res.status_code == 200, enc_res.text
    enc_data = enc_res.json()
    assert enc_data["encounter_number"] == "ENC-2026-9901"
    assert enc_data["department"] == "Cardiology"


def test_abac_sensitivity_and_break_glass_override(client, medical_users, db_session, root_folder_id):
    """Test ABAC psychiatric record lockout and Emergency Break-Glass override bypass."""
    from tests.conftest import _auth, _login

    # Seed Patient
    patient = Patient(
        mrn="MRN-BG-001",
        first_name="John",
        last_name="Doe",
        dob=now() - timedelta(days=365 * 30),
        gender="M",
        created_by=medical_users["doctor"].id,
    )
    doc = Document(
        name="Psychiatric_Evaluation.pdf",
        title="Confidential Psychiatric Consultation",
        file_path="medical/MRN-BG-001/psych_eval.pdf",
        folder_id=root_folder_id,
        created_by=medical_users["doctor"].id,
        status="active",
    )
    db_session.add_all([patient, doc])
    db_session.commit()
    db_session.refresh(patient)
    db_session.refresh(doc)

    med_doc = MedicalDocument(
        patient_id=patient.id,
        document_id=doc.id,
        clinical_category="clinical_note",
        sensitivity_level="psychiatric",
        created_by=medical_users["doctor"].id,
    )
    db_session.add(med_doc)
    db_session.commit()

    # 1. Nurse accesses patient records (Restricted!)
    nurse_headers = _auth(_login(client, "nurse_jackie", "nurse123"))
    list_res1 = client.get(f"/api/medical/patients/{patient.id}/documents", headers=nurse_headers)
    assert list_res1.status_code == 200
    docs_data1 = list_res1.json()
    assert len(docs_data1) == 1
    assert docs_data1[0]["accessible"] is False
    assert "RESTRICTED" in docs_data1[0]["title"]

    # 2. Nurse triggers Emergency Break-Glass Override
    bg_res = client.post(
        "/api/medical/break-glass",
        headers=nurse_headers,
        json={
            "patient_id": patient.id,
            "document_id": doc.id,
            "emergency_rationale": "Acute altered mental status & suspected overdose in Trauma Bay 1",
        },
    )
    assert bg_res.status_code == 200, bg_res.text
    bg_data = bg_res.json()
    assert bg_data["alert_sent"] is True

    # 3. Nurse re-accesses patient records (Unlocked by Break-Glass!)
    list_res2 = client.get(f"/api/medical/patients/{patient.id}/documents", headers=nurse_headers)
    assert list_res2.status_code == 200
    docs_data2 = list_res2.json()
    assert docs_data2[0]["accessible"] is True
    assert docs_data2[0]["title"] == "Confidential Psychiatric Consultation"


def test_bedside_barcoded_document_ingestion(client, admin_user, db_session, root_folder_id):
    """Test bedside physical document scanning with barcode wristband/order matching."""
    from tests.conftest import _auth, _login

    headers = _auth(_login(client, "admin", "admin123"))

    # Seed Patient and Encounter
    patient = Patient(
        mrn="MRN-BARCODE-99",
        first_name="Lucas",
        last_name="Scott",
        dob=now() - timedelta(days=365 * 25),
        created_by=admin_user.id,
    )
    db_session.add(patient)
    db_session.commit()
    db_session.refresh(patient)

    enc = PatientEncounter(
        encounter_number="ENC-BARCODE-99",
        patient_id=patient.id,
        encounter_type="emergency",
        status="admitted",
        created_by=admin_user.id,
    )
    db_session.add(enc)
    db_session.commit()

    sample_pdf_bytes = b"%PDF-1.4 Bedside Scanned Order Content"

    res = client.post(
        "/api/medical/bedside-ingest",
        headers=headers,
        data={
            "folder_id": root_folder_id,
            "barcode_text": "MRN:MRN-BARCODE-99|ENC:ENC-BARCODE-99",
        },
        files={"file": ("scanned_order.pdf", sample_pdf_bytes, "application/pdf")},
    )
    assert res.status_code == 200, res.text
    data = res.json()
    assert data["status"] == "ingested"
    assert data["patient_mrn"] == "MRN-BARCODE-99"
    assert data["encounter_number"] == "ENC-BARCODE-99"


def test_hl7_v2_and_fhir_interoperability(client, admin_user, db_session, root_folder_id):
    """Test parsing HL7 v2 messages and exporting standard FHIR DocumentReference resources."""
    from tests.conftest import _auth, _login

    headers = _auth(_login(client, "admin", "admin123"))

    # 1. Ingest HL7 v2 ADT^A01 Message
    hl7_msg = (
        "MSH|^~\\&|EPIC|HOSPITAL|NEWTON_EDMS|ARCHIVE|20260601120000||ADT^A01|MSG-998811|P|2.5\r"
        "PID|1||MRN-HL7-5566||Sterling^Archer||19850115|M\r"
        "PV1|1|I|ICU^01^02||||Dr^House^Gregory|||||||||||ENC-HL7-101\r"
    )
    hl7_res = client.post(
        "/api/medical/hl7/ingest",
        headers=headers,
        json={"hl7_message": hl7_msg},
    )
    assert hl7_res.status_code == 200, hl7_res.text
    hl7_data = hl7_res.json()
    assert hl7_data["status"] == "processed"
    assert hl7_data["hl7_parsed"]["patient"]["mrn"] == "MRN-HL7-5566"
    assert hl7_data["hl7_parsed"]["patient"]["last_name"] == "Sterling"

    # 2. Export FHIR DocumentReference
    pat = db_session.query(Patient).filter(Patient.mrn == "MRN-HL7-5566").first()
    assert pat is not None

    doc = Document(
        name="Discharge_Summary.pdf",
        title="Hospital Discharge Summary",
        file_path="medical/MRN-HL7-5566/discharge.pdf",
        folder_id=root_folder_id,
        created_by=admin_user.id,
        status="active",
    )
    db_session.add(doc)
    db_session.commit()
    db_session.refresh(doc)

    med_doc = MedicalDocument(
        patient_id=pat.id,
        document_id=doc.id,
        clinical_category="discharge_summary",
        sensitivity_level="standard",
        is_signed=True,
        created_by=admin_user.id,
    )
    db_session.add(med_doc)
    db_session.commit()
    db_session.refresh(med_doc)

    fhir_res = client.get(f"/api/medical/fhir/DocumentReference/{med_doc.id}", headers=headers)
    assert fhir_res.status_code == 200, fhir_res.text
    fhir_data = fhir_res.json()
    assert fhir_data["resourceType"] == "DocumentReference"
    assert fhir_data["docStatus"] == "final"
    assert "MRN-HL7-5566" in fhir_data["subject"]["reference"]


def test_dicom_study_imaging_metadata(client, admin_user, db_session, root_folder_id):
    """Test registering DICOM CT/MRI imaging studies with PACS metadata."""
    from tests.conftest import _auth, _login

    headers = _auth(_login(client, "admin", "admin123"))

    patient = Patient(
        mrn="MRN-DICOM-01",
        first_name="Dana",
        last_name="Scully",
        dob=now() - timedelta(days=365 * 35),
        created_by=admin_user.id,
    )
    doc = Document(
        name="Chest_CT_Slice.dcm",
        title="High Resolution Chest CT",
        file_path="medical/MRN-DICOM-01/ct_chest.dcm",
        folder_id=root_folder_id,
        created_by=admin_user.id,
        status="active",
    )
    db_session.add_all([patient, doc])
    db_session.commit()
    db_session.refresh(patient)
    db_session.refresh(doc)

    res = client.post(
        "/api/medical/dicom",
        headers=headers,
        json={
            "study_instance_uid": "1.2.840.113619.2.55.3.2831178.441.12345",
            "patient_id": patient.id,
            "document_id": doc.id,
            "modality": "CT",
            "body_part_examined": "CHEST",
            "series_count": 4,
            "instance_count": 320,
        },
    )
    assert res.status_code == 200, res.text
    data = res.json()
    assert data["modality"] == "CT"
    assert data["body_part_examined"] == "CHEST"
    assert data["instance_count"] == 320


def test_informed_consent_and_pdf_generation(client, admin_user, db_session):
    """Test digital bedside informed consent capture and certified PDF generation."""
    from tests.conftest import _auth, _login

    headers = _auth(_login(client, "admin", "admin123"))

    patient = Patient(
        mrn="MRN-CONSENT-01",
        first_name="Walter",
        last_name="Bishop",
        dob=now() - timedelta(days=365 * 60),
        created_by=admin_user.id,
    )
    db_session.add(patient)
    db_session.commit()
    db_session.refresh(patient)

    # 1. Submit Signed Informed Consent
    c_res = client.post(
        "/api/medical/consents",
        headers=headers,
        json={
            "patient_id": patient.id,
            "consent_type": "surgical",
            "procedure_name": "Laparoscopic Appendectomy",
            "signer_name": "Walter Bishop",
            "signer_relationship": "patient",
            "signature_data": "data:image/svg+xml;base64,PHN2ZyB4bWxucz0...",
            "witness_name": "Nurse Astrid Farnsworth",
        },
    )
    assert c_res.status_code == 200, c_res.text
    consent_id = c_res.json()["id"]

    # 2. Download Consent Form PDF
    pdf_res = client.get(f"/api/medical/consents/{consent_id}/pdf", headers=headers)
    assert pdf_res.status_code == 200
    assert pdf_res.headers["content-type"] == "application/pdf"
    assert len(pdf_res.content) > 1000
    assert pdf_res.content.startswith(b"%PDF")


def test_clinical_idp_chart_extraction(client, admin_user):
    """Test Intelligent Clinical IDP extraction from doctor chart note."""
    from tests.conftest import _auth, _login

    headers = _auth(_login(client, "admin", "admin123"))

    chart_note = """
    MASSACHUSETTS GENERAL HOSPITAL - PROGRESS NOTE
    Patient Name: Olivia Dunham
    MRN: MRN-MGH-99221
    Attending Physician: Dr. Walter Bishop

    VITAL SIGNS:
    BP: 124/82
    Pulse: 74 bpm
    Temp: 98.6 F
    SpO2: 99%

    Chief Complaint: Persistent migraine and mild photophobia
    Diagnoses ICD-10: G43.909 (Migraine), R51.9 (Headache)
    Allergies: Penicillin, Sulfa drugs
    Rx: Sumatriptan 50mg PO PRN, Acetaminophen 500mg
    """

    res = client.post(
        "/api/medical/idp/extract",
        headers=headers,
        json={"text": chart_note},
    )
    assert res.status_code == 200, res.text
    data = res.json()
    assert data["patient_name"] == "Olivia Dunham"
    assert data["mrn"] == "MRN-MGH-99221"
    assert data["vital_signs"]["blood_pressure"] == "124/82"
    assert data["vital_signs"]["heart_rate"] == "74 bpm"
    assert "G43.909" in data["icd10_diagnoses"]
    assert len(data["allergies"]) >= 2
