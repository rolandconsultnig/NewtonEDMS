"""HL7 (v2.x) and FHIR Interoperability Engine for EHR / LIMS Integration."""
from __future__ import annotations

import logging
from datetime import datetime
from typing import Any

from sqlalchemy.orm import Session

from app.database import now
from app.models import Document, MedicalDocument, Patient, PatientEncounter, User

logger = logging.getLogger("newtonedms.medical.hl7")


def parse_hl7_v2_message(hl7_text: str) -> dict[str, Any]:
    """
    Parse standard HL7 v2.x message (ADT^A01, ORU^R01, MDM^T02).
    Extracts MSH, PID, PV1, OBX, and TXA segments.
    """
    result: dict[str, Any] = {
        "message_type": "",
        "message_control_id": "",
        "patient": {
            "mrn": "",
            "first_name": "",
            "last_name": "",
            "dob": "",
            "gender": "",
        },
        "encounter": {
            "encounter_number": "",
            "department": "",
            "attending_physician": "",
        },
        "observations": [],
        "document_text": "",
    }

    if not hl7_text:
        return result

    lines = [l.strip() for l in hl7_text.splitlines() if l.strip()]

    for line in lines:
        fields = line.split("|")
        seg = fields[0].upper()

        if seg == "MSH" and len(fields) > 9:
            result["message_type"] = fields[8]  # e.g. ADT^A01 or ORU^R01
            result["message_control_id"] = fields[9]

        elif seg == "PID" and len(fields) > 5:
            # PID-3: Patient Identifier (MRN)
            result["patient"]["mrn"] = fields[3].split("^")[0] if len(fields) > 3 else ""
            # PID-5: Patient Name (Last^First^Middle)
            if len(fields) > 5:
                name_parts = fields[5].split("^")
                result["patient"]["last_name"] = name_parts[0] if len(name_parts) > 0 else ""
                result["patient"]["first_name"] = name_parts[1] if len(name_parts) > 1 else ""
            # PID-7: DOB (YYYYMMDD)
            if len(fields) > 7 and fields[7]:
                dob_raw = fields[7]
                if len(dob_raw) >= 8:
                    result["patient"]["dob"] = f"{dob_raw[:4]}-{dob_raw[4:6]}-{dob_raw[6:8]}"
            # PID-8: Gender
            if len(fields) > 8:
                result["patient"]["gender"] = fields[8]

        elif seg == "PV1" and len(fields) > 19:
            # PV1-3: Assigned Patient Location / Dept
            result["encounter"]["department"] = fields[3].split("^")[0] if len(fields) > 3 else ""
            # PV1-7: Attending Doctor (ID^Last^First)
            if len(fields) > 7:
                doc_parts = fields[7].split("^")
                result["encounter"]["attending_physician"] = f"Dr. {doc_parts[1]} {doc_parts[2]}" if len(doc_parts) > 2 else fields[7]
            # PV1-19: Visit Number / Encounter ID
            if len(fields) > 19:
                result["encounter"]["encounter_number"] = fields[19].split("^")[0]

        elif seg == "OBX" and len(fields) > 5:
            # OBX-3: Observation Identifier (e.g. 718-7^Hemoglobin)
            # OBX-5: Observation Value
            # OBX-6: Units
            obs_id = fields[3].split("^")[1] if "^" in fields[3] else fields[3]
            obs_val = fields[5] if len(fields) > 5 else ""
            obs_units = fields[6] if len(fields) > 6 else ""
            result["observations"].append({
                "test_name": obs_id,
                "value": obs_val,
                "units": obs_units,
            })

        elif seg == "TXA" and len(fields) > 5:
            # Document details
            if len(fields) > 16:
                result["document_text"] = fields[16]

    return result


def export_fhir_document_reference(
    patient: Patient,
    encounter: PatientEncounter | None,
    med_doc: MedicalDocument,
    doc: Document,
    base_url: str = "https://hospital.health.org/fhir",
) -> dict[str, Any]:
    """
    Generate FHIR R4 standard DocumentReference resource.
    """
    return {
        "resourceType": "DocumentReference",
        "id": f"docref-{med_doc.id}",
        "status": "current",
        "docStatus": "final" if med_doc.is_signed else "preliminary",
        "type": {
            "coding": [{
                "system": "http://loinc.org",
                "code": "11488-4",
                "display": med_doc.clinical_category.replace("_", " ").title(),
            }]
        },
        "subject": {
            "reference": f"Patient/{patient.mrn}",
            "display": f"{patient.first_name} {patient.last_name}",
        },
        "context": {
            "encounter": [{"reference": f"Encounter/{encounter.encounter_number}"}] if encounter else []
        },
        "content": [{
            "attachment": {
                "contentType": doc.mime or "application/pdf",
                "url": f"{base_url}/documents/{doc.id}/download",
                "title": doc.title or doc.name,
                "size": doc.size,
            }
        }],
        "securityLabel": [{
            "coding": [{
                "system": "http://terminology.hl7.org/CodeSystem/v3-Confidentiality",
                "code": "R" if med_doc.sensitivity_level != "standard" else "N",
                "display": med_doc.sensitivity_level.title(),
            }]
        }],
    }
