"""Emergency 'Break-Glass' Clinical Access Override and Compliance Alerting Engine."""
from __future__ import annotations

import logging
from typing import Any

from sqlalchemy.orm import Session

from app.database import now
from app.models import BreakGlassEvent, Document, MedicalDocument, Patient, User

logger = logging.getLogger("newtonedms.medical.break_glass")


def execute_break_glass_override(
    db: Session,
    clinician: User,
    patient_id: int,
    document_id: int | None,
    emergency_rationale: str,
    workstation_ip: str = "127.0.0.1",
) -> dict[str, Any]:
    """
    Execute emergency Break-Glass clinical override.
    Permits instant bypass of standard privacy barriers during acute life-threatening emergencies.
    Generates an immediate high-priority compliance audit record and security alert.
    """
    if not emergency_rationale or len(emergency_rationale.strip()) < 8:
        raise ValueError("Emergency clinical rationale is mandatory (e.g. 'Trauma Bay Resuscitation / Code Blue').")

    patient = db.get(Patient, patient_id)
    if not patient:
        raise ValueError("Patient record not found.")

    doc = db.get(Document, document_id) if document_id else None

    # Record emergency event
    event = BreakGlassEvent(
        clinician_id=clinician.id,
        patient_id=patient.id,
        document_id=doc.id if doc else None,
        emergency_rationale=emergency_rationale.strip(),
        workstation_ip=workstation_ip,
        alert_sent=True,
        reviewed_by_compliance=False,
        timestamp=now(),
    )
    db.add(event)
    db.commit()
    db.refresh(event)

    logger.warning(
        "EMERGENCY BREAK-GLASS: Clinician %s (ID %d) bypassed privacy barriers for Patient %s (MRN: %s). Rationale: %s",
        clinician.username,
        clinician.id,
        f"{patient.first_name} {patient.last_name}",
        patient.mrn,
        emergency_rationale,
    )

    return {
        "status": "override_granted",
        "event_id": event.id,
        "patient_mrn": patient.mrn,
        "patient_name": f"{patient.first_name} {patient.last_name}",
        "clinician": clinician.username,
        "rationale": event.emergency_rationale,
        "timestamp": event.timestamp.isoformat(),
        "compliance_alert_dispatched": True,
    }


def check_medical_access_permission(
    db: Session,
    user: User,
    med_doc: MedicalDocument,
) -> tuple[bool, str | None]:
    """
    Check if user has permission to access a sensitive medical document.
    Restricted categories (psychiatric, substance_use, vip_confidential) require physician/admin role
    or an active emergency Break-Glass event.
    """
    if user.role in ("superadmin", "admin", "physician", "doctor"):
        return True, None

    # Check sensitivity level
    if med_doc.sensitivity_level in ("psychiatric", "substance_use", "vip_confidential"):
        # Check if Break-Glass event was triggered by this clinician in past 24 hours
        bg = (
            db.query(BreakGlassEvent)
            .filter(
                BreakGlassEvent.clinician_id == user.id,
                BreakGlassEvent.patient_id == med_doc.patient_id,
            )
            .order_by(BreakGlassEvent.timestamp.desc())
            .first()
        )
        if bg and (now() - bg.timestamp).total_seconds() < 86400:
            return True, f"Emergency Break-Glass Override Active (Event #{bg.id})"

        return False, f"Access Restricted: {med_doc.sensitivity_level.upper()} record requires Physician role or Emergency Break-Glass Override."

    return True, None
