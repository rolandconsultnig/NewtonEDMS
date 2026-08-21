"""Duplicate Invoice Detection Engine to prevent double-payment and fraud."""
from __future__ import annotations

import difflib
from datetime import datetime, timedelta
from typing import Any

from sqlalchemy.orm import Session

from app.models import InvoiceRecord


def detect_duplicate_invoice(
    db: Session,
    vendor_name: str,
    invoice_number: str,
    total_amount: float,
    vendor_tax_id: str | None = None,
    invoice_date: datetime | None = None,
    current_invoice_id: int | None = None,
) -> dict[str, Any]:
    """
    Evaluate candidate invoice against existing database records for potential duplicates.
    Scores confidence from 0 to 100% and provides match reasons.
    """
    candidates_query = db.query(InvoiceRecord)
    if current_invoice_id:
        candidates_query = candidates_query.filter(InvoiceRecord.id != current_invoice_id)

    candidates = candidates_query.all()
    if not candidates:
        return {"is_duplicate": False, "confidence": 0, "duplicate_of_id": None, "reasons": []}

    best_match_id = None
    best_score = 0
    match_reasons: list[str] = []

    norm_vendor = (vendor_name or "").strip().lower()
    norm_inv_num = (invoice_number or "").strip().lower()

    for cand in candidates:
        cand_vendor = (cand.vendor_name or "").strip().lower()
        cand_inv_num = (cand.invoice_number or "").strip().lower()
        cand_tax_id = (cand.vendor_tax_id or "").strip().lower()
        cand_amount = float(cand.total_amount or 0.0)

        score = 0
        reasons = []

        # 1. Exact Vendor Tax ID + Invoice Number Match (Definitive Duplicate)
        if vendor_tax_id and cand_tax_id and vendor_tax_id.lower() == cand_tax_id:
            if norm_inv_num and norm_inv_num == cand_inv_num:
                score = 100
                reasons.append(f"Exact Tax ID ({vendor_tax_id}) and Invoice Number ({invoice_number}) match.")

        # 2. Vendor Name Similarity + Exact Invoice Number Match
        vendor_sim = difflib.SequenceMatcher(None, norm_vendor, cand_vendor).ratio()
        if norm_inv_num and norm_inv_num == cand_inv_num and vendor_sim > 0.8:
            score = max(score, int(vendor_sim * 95))
            reasons.append(f"Matching Invoice Number '{invoice_number}' with {int(vendor_sim*100)}% vendor name similarity.")

        # 3. Matching Vendor + Exact Amount + Similar Date
        if vendor_sim > 0.85 and abs(total_amount - cand_amount) < 0.01:
            date_close = False
            if invoice_date and cand.invoice_date:
                diff_days = abs((invoice_date - cand.invoice_date).days)
                if diff_days <= 7:
                    date_close = True
                    reasons.append(f"Identical amount (${total_amount:,.2f}) and invoice date within {diff_days} days.")
            if date_close:
                score = max(score, 85)
            elif not reasons:
                score = max(score, 60)
                reasons.append(f"Identical amount (${total_amount:,.2f}) for same vendor.")

        if score > best_score:
            best_score = score
            best_match_id = cand.id
            match_reasons = reasons

    is_duplicate = best_score >= 80

    return {
        "is_duplicate": is_duplicate,
        "confidence": best_score,
        "duplicate_of_id": best_match_id if is_duplicate else None,
        "reasons": match_reasons,
    }
