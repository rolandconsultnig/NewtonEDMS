"""Insurance Document Generator (Policy Binders, FNOL Acknowledgment, Settlement Statements)."""
from __future__ import annotations

import logging
from typing import Any
from fpdf import FPDF

from app.database import now
from app.models import InsuranceClaim, InsurancePolicy

logger = logging.getLogger("newtonedms.insurance.docs")


def generate_settlement_statement_pdf(
    claim: InsuranceClaim,
    policy: InsurancePolicy,
    custom_notes: str = "",
) -> bytes:
    """Generate official Insurance Settlement Explanation & Payout Statement PDF."""
    pdf = FPDF()
    pdf.add_page()
    pdf.set_auto_page_break(auto=True, margin=15)

    # Header
    pdf.set_font("Helvetica", "B", 16)
    pdf.set_text_color(24, 43, 73)
    pdf.cell(0, 10, "OFFICIAL INSURANCE SETTLEMENT STATEMENT", align="C", new_x="LMARGIN", new_y="NEXT")
    pdf.set_font("Helvetica", "I", 10)
    pdf.set_text_color(100, 100, 100)
    pdf.cell(0, 6, f"Generated on {now().strftime('%B %d, %Y')} | Claim Centric EDMS", align="C", new_x="LMARGIN", new_y="NEXT")
    pdf.ln(5)

    # Policy & Claim Details Box
    pdf.set_fill_color(245, 247, 250)
    pdf.rect(10, pdf.get_y(), 190, 45, "F")
    pdf.set_xy(15, pdf.get_y() + 4)

    pdf.set_font("Helvetica", "B", 11)
    pdf.set_text_color(30, 30, 30)
    pdf.cell(90, 6, f"Policy Number: {policy.policy_number}")
    pdf.cell(90, 6, f"Claim Number: {claim.claim_number}", new_x="LMARGIN", new_y="NEXT")
    pdf.set_x(15)

    pdf.set_font("Helvetica", "", 10)
    pdf.cell(90, 6, f"Insured: {policy.insured_name}")
    pdf.cell(90, 6, f"Claimant: {claim.claimant_name}", new_x="LMARGIN", new_y="NEXT")
    pdf.set_x(15)

    pdf.cell(90, 6, f"Loss Type: {claim.loss_type.replace('_', ' ').title()}")
    pdf.cell(90, 6, f"Loss Date: {claim.loss_date.strftime('%Y-%m-%d') if claim.loss_date else 'N/A'}", new_x="LMARGIN", new_y="NEXT")
    pdf.set_x(15)

    pdf.cell(90, 6, f"Coverage Limit: ${policy.coverage_limit:,.2f}")
    pdf.cell(90, 6, f"Deductible: ${policy.deductible:,.2f}", new_x="LMARGIN", new_y="NEXT")
    pdf.ln(10)

    # Adjudication & Payout Table
    pdf.set_font("Helvetica", "B", 12)
    pdf.set_text_color(24, 43, 73)
    pdf.cell(0, 8, "Settlement Adjudication Summary", new_x="LMARGIN", new_y="NEXT")

    pdf.set_font("Helvetica", "B", 10)
    pdf.set_fill_color(230, 235, 245)
    pdf.cell(130, 8, "Item Description", border=1, fill=True)
    pdf.cell(60, 8, "Amount ($)", border=1, fill=True, align="R", new_x="LMARGIN", new_y="NEXT")

    pdf.set_font("Helvetica", "", 10)
    pdf.cell(130, 8, "Gross Assessed Loss / Repair Estimate", border=1)
    pdf.cell(60, 8, f"${claim.estimated_loss:,.2f}", border=1, align="R", new_x="LMARGIN", new_y="NEXT")

    pdf.cell(130, 8, f"Less Policy Deductible ({policy.policy_number})", border=1)
    pdf.cell(60, 8, f"-${policy.deductible:,.2f}", border=1, align="R", new_x="LMARGIN", new_y="NEXT")

    pdf.set_font("Helvetica", "B", 11)
    pdf.set_fill_color(235, 250, 235)
    pdf.cell(130, 10, "NET APPROVED SETTLEMENT PAYOUT", border=1, fill=True)
    pdf.cell(60, 10, f"${claim.settlement_amount:,.2f}", border=1, fill=True, align="R", new_x="LMARGIN", new_y="NEXT")
    pdf.ln(6)

    # Adjudication Notes
    if custom_notes or claim.notes:
        pdf.set_font("Helvetica", "B", 10)
        pdf.cell(0, 6, "Adjuster / Underwriter Notes:", new_x="LMARGIN", new_y="NEXT")
        pdf.set_font("Helvetica", "", 9)
        pdf.multi_cell(0, 5, (custom_notes or claim.notes).encode("latin-1", "replace").decode("latin-1"))
        pdf.ln(4)

    # Certification Sign-Off
    pdf.ln(10)
    pdf.set_font("Helvetica", "I", 9)
    pdf.set_text_color(100, 100, 100)
    pdf.cell(0, 5, "This document certifies that the claim above has been evaluated and approved under the terms of the policy.", new_x="LMARGIN", new_y="NEXT")
    pdf.cell(0, 5, "Authorized Claims Department Signature | WORM Compliant Audit Record", new_x="LMARGIN", new_y="NEXT")

    return bytes(pdf.output())
