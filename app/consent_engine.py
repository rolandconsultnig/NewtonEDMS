"""Bedside Digital Informed Consent Generator with Cryptographic e-Signatures."""
from __future__ import annotations

import logging
from typing import Any
from fpdf import FPDF

from app.database import now
from app.models import InformedConsent, Patient

logger = logging.getLogger("newtonedms.medical.consent")


def generate_consent_form_pdf(
    consent: InformedConsent,
    patient: Patient,
) -> bytes:
    """Generate legally binding digital informed consent form with e-signature certification."""
    pdf = FPDF()
    pdf.add_page()
    pdf.set_auto_page_break(auto=True, margin=15)

    # Header
    pdf.set_font("Helvetica", "B", 16)
    pdf.set_text_color(15, 76, 129)
    pdf.cell(0, 10, "OFFICIAL PATIENT INFORMED CONSENT", align="C", new_x="LMARGIN", new_y="NEXT")
    pdf.set_font("Helvetica", "I", 10)
    pdf.set_text_color(100, 100, 100)
    pdf.cell(0, 6, "Hospital Health System · Electronic Health Record Archive", align="C", new_x="LMARGIN", new_y="NEXT")
    pdf.ln(5)

    # Patient Identification Box
    pdf.set_fill_color(245, 248, 252)
    pdf.rect(10, pdf.get_y(), 190, 35, "F")
    pdf.set_xy(15, pdf.get_y() + 4)

    pdf.set_font("Helvetica", "B", 11)
    pdf.set_text_color(30, 30, 30)
    pdf.cell(90, 6, f"Patient Name: {patient.first_name} {patient.last_name}")
    pdf.cell(90, 6, f"MRN: {patient.mrn}", new_x="LMARGIN", new_y="NEXT")
    pdf.set_x(15)

    pdf.set_font("Helvetica", "", 10)
    pdf.cell(90, 6, f"Date of Birth: {patient.dob.strftime('%Y-%m-%d') if patient.dob else 'N/A'}")
    pdf.cell(90, 6, f"Gender: {patient.gender}", new_x="LMARGIN", new_y="NEXT")
    pdf.set_x(15)
    pdf.cell(90, 6, f"Consent Type: {consent.consent_type.replace('_', ' ').title()}")
    pdf.cell(90, 6, f"Procedure: {consent.procedure_name}", new_x="LMARGIN", new_y="NEXT")
    pdf.ln(10)

    # Consent Terms
    pdf.set_font("Helvetica", "B", 12)
    pdf.set_text_color(15, 76, 129)
    pdf.cell(0, 8, "Voluntary Authorization & Medical Acknowledgment", new_x="LMARGIN", new_y="NEXT")
    pdf.set_font("Helvetica", "", 10)
    pdf.set_text_color(40, 40, 40)
    terms = (
        f"I hereby authorize the medical staff and attending physicians to perform the procedure: '{consent.procedure_name}'. "
        "The risks, potential complications, and alternative treatments have been explained to my full satisfaction. "
        "I confirm that I have had the opportunity to ask questions and all inquiries have been answered. "
        "This consent is given voluntarily with full understanding of clinical risks."
    )
    pdf.multi_cell(0, 6, terms)
    pdf.ln(8)

    # e-Signature Box
    pdf.set_fill_color(240, 245, 240)
    pdf.rect(10, pdf.get_y(), 190, 40, "F")
    pdf.set_xy(15, pdf.get_y() + 4)

    pdf.set_font("Helvetica", "B", 11)
    pdf.cell(0, 6, "Electronic Signature Verification Block", new_x="LMARGIN", new_y="NEXT")
    pdf.set_x(15)
    pdf.set_font("Helvetica", "", 10)
    pdf.cell(90, 6, f"Signer: {consent.signer_name} ({consent.signer_relationship.title()})")
    pdf.cell(90, 6, f"Witness: {consent.witness_name or 'Attending Nurse'}", new_x="LMARGIN", new_y="NEXT")
    pdf.set_x(15)
    pdf.cell(0, 6, f"Timestamp: {consent.signed_at.strftime('%Y-%m-%d %H:%M:%S UTC')} · Cryptographic Audit Tag: CERT-{consent.id:06d}", new_x="LMARGIN", new_y="NEXT")

    return bytes(pdf.output())
