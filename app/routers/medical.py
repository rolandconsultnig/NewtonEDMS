"""Healthcare & Medical EDMS Router: Patients, Encounters, DICOM, HL7/FHIR, Break-Glass & Consents."""
from __future__ import annotations

import logging
from datetime import datetime, timedelta
from typing import Any

from fastapi import APIRouter, Depends, File, Form, HTTPException, Query, Request, UploadFile, status
from fastapi.responses import Response
from sqlalchemy.orm import Session

from app.break_glass_engine import check_medical_access_permission, execute_break_glass_override
from app.clinical_idp_parser import parse_clinical_chart_text
from app.consent_engine import generate_consent_form_pdf
from app.database import BASE_DIR, get_db, now
from app.hl7_fhir_engine import export_fhir_document_reference, parse_hl7_v2_message
from app.medical_engine import calculate_statutory_retention_years, ingest_bedside_barcoded_document
from app.models import (
    BreakGlassEvent,
    DicomStudy,
    Document,
    InformedConsent,
    MedicalDocument,
    Patient,
    PatientEncounter,
    User,
)
from app.schemas import (
    BreakGlassCreate,
    BreakGlassOut,
    DicomStudyCreate,
    DicomStudyOut,
    InformedConsentCreate,
    InformedConsentOut,
    MedicalDocumentCreate,
    MedicalDocumentOut,
    PatientEncounterCreate,
    PatientEncounterOut,
    PatientCreate,
    PatientOut,
)
from app.security import get_current_user, require_role

router = APIRouter(prefix="/api/medical", tags=["medical"])


# =============================================================================
# 1. Master Patient Index (MPI) & Electronic Health Records
# =============================================================================


@router.post("/patients", response_model=PatientOut)
def create_patient(
    payload: PatientCreate,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    existing = db.query(Patient).filter(Patient.mrn == payload.mrn).first()
    if existing:
        raise HTTPException(status_code=400, detail=f"MRN '{payload.mrn}' already registered.")

    patient = Patient(
        mrn=payload.mrn,
        first_name=payload.first_name,
        last_name=payload.last_name,
        dob=payload.dob,
        gender=payload.gender,
        blood_type=payload.blood_type,
        primary_physician=payload.primary_physician,
        insurance_id=payload.insurance_id,
        metadata_json=payload.metadata_json,
        created_by=user.id,
        created_at=now(),
    )
    db.add(patient)
    db.commit()
    db.refresh(patient)
    return patient


@router.get("/patients", response_model=list[PatientOut])
def list_patients(
    mrn: str | None = None,
    name: str | None = None,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    q = db.query(Patient)
    if mrn:
        q = q.filter(Patient.mrn.ilike(f"%{mrn}%"))
    if name:
        q = q.filter((Patient.first_name.ilike(f"%{name}%")) | (Patient.last_name.ilike(f"%{name}%")))
    return q.order_by(Patient.last_name.asc()).all()


@router.get("/patients/{patient_id}", response_model=PatientOut)
def get_patient(
    patient_id: int,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    patient = db.get(Patient, patient_id)
    if not patient:
        raise HTTPException(status_code=404, detail="Patient record not found.")
    return patient


# =============================================================================
# 2. Patient Encounters & Admissions
# =============================================================================


@router.post("/encounters", response_model=PatientEncounterOut)
def create_encounter(
    payload: PatientEncounterCreate,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    existing = db.query(PatientEncounter).filter(PatientEncounter.encounter_number == payload.encounter_number).first()
    if existing:
        raise HTTPException(status_code=400, detail=f"Encounter '{payload.encounter_number}' already exists.")

    encounter = PatientEncounter(
        encounter_number=payload.encounter_number,
        patient_id=payload.patient_id,
        encounter_type=payload.encounter_type,
        admission_date=payload.admission_date or now(),
        department=payload.department,
        attending_physician=payload.attending_physician,
        chief_complaint=payload.chief_complaint,
        status="admitted",
        created_by=user.id,
        created_at=now(),
    )
    db.add(encounter)
    db.commit()
    db.refresh(encounter)
    return encounter


@router.get("/encounters", response_model=list[PatientEncounterOut])
def list_encounters(
    patient_id: int | None = None,
    department: str | None = None,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    q = db.query(PatientEncounter)
    if patient_id:
        q = q.filter(PatientEncounter.patient_id == patient_id)
    if department:
        q = q.filter(PatientEncounter.department == department)
    return q.order_by(PatientEncounter.admission_date.desc()).all()


# =============================================================================
# 3. Medical Documents & ABAC Sensitivity Access
# =============================================================================


@router.post("/documents", response_model=MedicalDocumentOut)
def create_medical_document(
    payload: MedicalDocumentCreate,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    doc = db.get(Document, payload.document_id)
    if not doc:
        raise HTTPException(status_code=404, detail="Document not found.")

    med_doc = MedicalDocument(
        patient_id=payload.patient_id,
        encounter_id=payload.encounter_id,
        document_id=payload.document_id,
        clinical_category=payload.clinical_category,
        sensitivity_level=payload.sensitivity_level,
        icd10_codes=payload.icd10_codes,
        created_by=user.id,
        created_at=now(),
    )
    db.add(med_doc)
    db.commit()
    db.refresh(med_doc)
    return med_doc


@router.get("/patients/{patient_id}/documents")
def list_patient_documents(
    patient_id: int,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    patient = db.get(Patient, patient_id)
    if not patient:
        raise HTTPException(status_code=404, detail="Patient not found.")

    med_docs = db.query(MedicalDocument).filter(MedicalDocument.patient_id == patient_id).all()
    results = []

    for m in med_docs:
        allowed, reason = check_medical_access_permission(db, user, m)
        d = db.get(Document, m.document_id)
        if allowed:
            results.append({
                "id": m.id,
                "document_id": m.document_id,
                "title": d.title if d else "Clinical Record",
                "name": d.name if d else "record.pdf",
                "clinical_category": m.clinical_category,
                "sensitivity_level": m.sensitivity_level,
                "icd10_codes": m.icd10_codes,
                "is_signed": m.is_signed,
                "accessible": True,
                "created_at": m.created_at,
            })
        else:
            results.append({
                "id": m.id,
                "document_id": m.document_id,
                "title": f"RESTRICTED RECORD ({m.sensitivity_level.upper()})",
                "clinical_category": m.clinical_category,
                "sensitivity_level": m.sensitivity_level,
                "accessible": False,
                "restriction_reason": reason,
                "created_at": m.created_at,
            })

    return results


# =============================================================================
# 4. Emergency "Break-Glass" Access Override
# =============================================================================


@router.post("/break-glass", response_model=BreakGlassOut)
def trigger_break_glass(
    payload: BreakGlassCreate,
    request: Request,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    client_ip = request.client.host if request.client else "127.0.0.1"
    try:
        res = execute_break_glass_override(
            db=db,
            clinician=user,
            patient_id=payload.patient_id,
            document_id=payload.document_id,
            emergency_rationale=payload.emergency_rationale,
            workstation_ip=client_ip,
        )
        return db.get(BreakGlassEvent, res["event_id"])
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))


@router.get("/break-glass/events", response_model=list[BreakGlassOut])
def list_break_glass_events(
    db: Session = Depends(get_db),
    user: User = Depends(require_role("superadmin", "admin", "compliance", "physician")),
):
    return db.query(BreakGlassEvent).order_by(BreakGlassEvent.timestamp.desc()).all()


# =============================================================================
# 5. Bedside Barcode Scanning & Physical Paper Ingestion
# =============================================================================


@router.post("/bedside-ingest")
async def api_bedside_ingest(
    folder_id: int = Form(...),
    barcode_text: str = Form(...),
    file: UploadFile = File(...),
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    content = await file.read()
    return ingest_bedside_barcoded_document(
        db=db,
        user=user,
        file_bytes=content,
        filename=file.filename or "bedside_scan.pdf",
        folder_id=folder_id,
        barcode_text=barcode_text,
    )


# =============================================================================
# 6. HL7 v2.x and FHIR Interoperability
# =============================================================================


@router.post("/hl7/ingest")
def api_ingest_hl7(
    payload: dict[str, Any],
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    hl7_text = payload.get("hl7_message", "")
    parsed = parse_hl7_v2_message(hl7_text)

    # If patient MRN is extracted and does not exist, auto-register
    if parsed["patient"]["mrn"]:
        pat = db.query(Patient).filter(Patient.mrn == parsed["patient"]["mrn"]).first()
        if not pat and parsed["patient"]["first_name"]:
            dob_dt = datetime.strptime(parsed["patient"]["dob"], "%Y-%m-%d") if parsed["patient"]["dob"] else now()
            pat = Patient(
                mrn=parsed["patient"]["mrn"],
                first_name=parsed["patient"]["first_name"],
                last_name=parsed["patient"]["last_name"],
                dob=dob_dt,
                gender=parsed["patient"]["gender"] or "U",
                created_by=user.id,
                created_at=now(),
            )
            db.add(pat)
            db.commit()
            db.refresh(pat)

    return {
        "status": "processed",
        "hl7_parsed": parsed,
    }


@router.get("/fhir/DocumentReference/{med_doc_id}")
def api_get_fhir_docref(
    med_doc_id: int,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    med_doc = db.get(MedicalDocument, med_doc_id)
    if not med_doc:
        raise HTTPException(status_code=404, detail="Medical document not found.")

    patient = db.get(Patient, med_doc.patient_id)
    encounter = db.get(PatientEncounter, med_doc.encounter_id) if med_doc.encounter_id else None
    doc = db.get(Document, med_doc.document_id)

    return export_fhir_document_reference(patient, encounter, med_doc, doc)


# =============================================================================
# 7. DICOM & PACS Medical Imaging
# =============================================================================


@router.post("/dicom", response_model=DicomStudyOut)
def create_dicom_study(
    payload: DicomStudyCreate,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    existing = db.query(DicomStudy).filter(DicomStudy.study_instance_uid == payload.study_instance_uid).first()
    if existing:
        raise HTTPException(status_code=400, detail="DICOM Study UID already registered.")

    study = DicomStudy(
        study_instance_uid=payload.study_instance_uid,
        patient_id=payload.patient_id,
        document_id=payload.document_id,
        modality=payload.modality,
        body_part_examined=payload.body_part_examined,
        series_count=payload.series_count,
        instance_count=payload.instance_count,
        metadata_json=payload.metadata_json,
        created_by=user.id,
        created_at=now(),
    )
    db.add(study)
    db.commit()
    db.refresh(study)
    return study


@router.get("/dicom", response_model=list[DicomStudyOut])
def list_dicom_studies(
    patient_id: int | None = None,
    modality: str | None = None,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    q = db.query(DicomStudy)
    if patient_id:
        q = q.filter(DicomStudy.patient_id == patient_id)
    if modality:
        q = q.filter(DicomStudy.modality == modality)
    return q.order_by(DicomStudy.created_at.desc()).all()


# =============================================================================
# 8. Bedside Digital Informed Consent
# =============================================================================


@router.post("/consents", response_model=InformedConsentOut)
def create_informed_consent(
    payload: InformedConsentCreate,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    consent = InformedConsent(
        patient_id=payload.patient_id,
        encounter_id=payload.encounter_id,
        consent_type=payload.consent_type,
        procedure_name=payload.procedure_name,
        signer_name=payload.signer_name,
        signer_relationship=payload.signer_relationship,
        signature_data=payload.signature_data,
        witness_name=payload.witness_name,
        signed_at=now(),
        created_by=user.id,
    )
    db.add(consent)
    db.commit()
    db.refresh(consent)
    return consent


@router.get("/consents/{consent_id}/pdf")
def get_consent_pdf(
    consent_id: int,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    consent = db.get(InformedConsent, consent_id)
    if not consent:
        raise HTTPException(status_code=404, detail="Consent record not found.")

    patient = db.get(Patient, consent.patient_id)
    pdf_bytes = generate_consent_form_pdf(consent, patient)

    return Response(
        content=pdf_bytes,
        media_type="application/pdf",
        headers={"Content-Disposition": f'attachment; filename="Consent_{patient.mrn}_{consent.id}.pdf"'},
    )


# =============================================================================
# 9. Intelligent Clinical IDP
# =============================================================================


@router.post("/idp/extract")
def api_medical_idp(
    payload: dict[str, Any],
    user: User = Depends(get_current_user),
):
    text = payload.get("text", "")
    return parse_clinical_chart_text(text)
