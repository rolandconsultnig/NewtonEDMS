"""Healthcare Medical Record Engine (Patient Indexing, Bedside Barcode Ingest & Retention)."""
from __future__ import annotations

import logging
import re
from datetime import datetime, timedelta
from typing import Any

from sqlalchemy.orm import Session

from app.database import BASE_DIR, now
from app.models import Document, MedicalDocument, Patient, PatientEncounter, User

logger = logging.getLogger("newtonedms.medical.engine")


def ingest_bedside_barcoded_document(
    db: Session,
    user: User,
    file_bytes: bytes,
    filename: str,
    folder_id: int,
    barcode_text: str | None = None,
) -> dict[str, Any]:
    """
    Ingest physical clinical order or chart scanned at bedside with barcode/QR identifier.
    Pattern: 'MRN:MRN-12345|ENC:ENC-9001' or 'PATIENT:MRN-12345'.
    Automatically maps document to Patient and Encounter.
    """
    mrn = ""
    enc_num = ""

    # Parse barcode string
    if barcode_text:
        mrn_m = re.search(r"(?:MRN|PATIENT)[:\s\-]+([A-Za-z0-9\-_]+)", barcode_text, re.IGNORECASE)
        if mrn_m:
            mrn = mrn_m.group(1).strip()

        enc_m = re.search(r"(?:ENC|ENCOUNTER)[:\s\-]+([A-Za-z0-9\-_]+)", barcode_text, re.IGNORECASE)
        if enc_m:
            enc_num = enc_m.group(1).strip()

    patient: Patient | None = None
    if mrn:
        patient = db.query(Patient).filter(Patient.mrn == mrn).first()

    encounter: PatientEncounter | None = None
    if enc_num:
        encounter = db.query(PatientEncounter).filter(PatientEncounter.encounter_number == enc_num).first()
    elif patient:
        # Get active encounter
        encounter = (
            db.query(PatientEncounter)
            .filter(PatientEncounter.patient_id == patient.id, PatientEncounter.status == "admitted")
            .order_by(PatientEncounter.admission_date.desc())
            .first()
        )

    # Save to storage
    rel_path = f"medical/{(patient.mrn if patient else 'unassigned')}/{filename}"
    target = BASE_DIR / "storage" / rel_path
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_bytes(file_bytes)

    doc = Document(
        name=filename,
        title=f"Bedside Scan - {patient.mrn if patient else 'Unknown'} - {filename}",
        file_path=str(rel_path).replace("\\", "/"),
        mime="application/pdf",
        size=len(file_bytes),
        folder_id=folder_id,
        created_by=user.id,
        created_at=now(),
        tags=f"medical,bedside-scan,{patient.mrn if patient else 'unassigned'}",
        status="active",
    )
    db.add(doc)
    db.commit()
    db.refresh(doc)

    med_doc: MedicalDocument | None = None
    if patient:
        med_doc = MedicalDocument(
            patient_id=patient.id,
            encounter_id=encounter.id if encounter else None,
            document_id=doc.id,
            clinical_category="physician_order",
            sensitivity_level="standard",
            created_by=user.id,
            created_at=now(),
        )
        db.add(med_doc)
        db.commit()
        db.refresh(med_doc)

    return {
        "status": "ingested",
        "document_id": doc.id,
        "patient_mrn": patient.mrn if patient else None,
        "patient_name": f"{patient.first_name} {patient.last_name}" if patient else None,
        "encounter_number": encounter.encounter_number if encounter else None,
        "clinical_category": med_doc.clinical_category if med_doc else "unclassified",
    }


def calculate_statutory_retention_years(patient: Patient) -> int:
    """
    Calculate statutory medical record retention period:
    - Adult patient: 7 to 10 years from last treatment date.
    - Pediatric patient: Retained until patient reaches 18 + 7 years (25 years from birth).
    """
    if not patient.dob:
        return 7

    age = (now() - patient.dob).days // 365
    if age < 18:
        # Pediatric retention: 18 - age + 7 years
        return max(7, (18 - age) + 7)
    return 7
