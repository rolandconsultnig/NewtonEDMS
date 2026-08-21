"""Automated 2-Way and 3-Way Matching Engine for Accounts Payable (AP)."""
from __future__ import annotations

import logging
from typing import Any

from sqlalchemy.orm import Session

from app.models import GoodsReceivedNote, InvoiceRecord, PurchaseOrder, User

logger = logging.getLogger("newtonedms.accounting.matching")


def perform_matching(
    db: Session,
    invoice_id: int,
    user: User,
    price_tolerance_pct: float = 2.0,
    qty_tolerance_pct: float = 0.0,
) -> dict[str, Any]:
    """
    Perform automated 2-Way or 3-Way matching between Vendor Invoice, PO, and GRN.
    - 2-Way Match: Invoice vs Purchase Order (Prices & Quantities ordered)
    - 3-Way Match: Invoice vs Purchase Order vs Goods Received Note (Warehouse delivery verification)
    """
    inv = db.get(InvoiceRecord, invoice_id)
    if not inv:
        raise ValueError("Invoice record not found.")

    po: PurchaseOrder | None = None
    if inv.po_number:
        po = db.query(PurchaseOrder).filter(PurchaseOrder.po_number == inv.po_number).first()

    grn: GoodsReceivedNote | None = None
    if inv.grn_number:
        grn = db.query(GoodsReceivedNote).filter(GoodsReceivedNote.grn_number == inv.grn_number).first()
    elif po and po.po_number:
        grn = db.query(GoodsReceivedNote).filter(GoodsReceivedNote.po_number == po.po_number).first()

    discrepancies: list[str] = []
    line_comparisons: list[dict[str, Any]] = []

    # 1. Check if PO exists
    if not po:
        inv.matching_status = "missing_po"
        inv.matching_notes = f"No matching Purchase Order found for PO reference '{inv.po_number or 'N/A'}'."
        db.commit()
        db.refresh(inv)
        return {
            "invoice_id": inv.id,
            "status": inv.matching_status,
            "match_type": "none",
            "notes": inv.matching_notes,
            "discrepancies": ["Missing PO reference"],
            "line_comparisons": [],
        }

    # 2. Total Amount & Price Matching (2-Way)
    po_total = float(po.total_amount or 0.0)
    inv_total = float(inv.total_amount or 0.0)
    price_diff = abs(inv_total - po_total)
    price_diff_pct = (price_diff / po_total * 100.0) if po_total > 0 else 0.0

    if price_diff_pct > price_tolerance_pct:
        discrepancies.append(
            f"Total invoice amount (${inv_total:,.2f}) exceeds PO (${po_total:,.2f}) by {price_diff_pct:.1f}% (Tolerance: ±{price_tolerance_pct}%)"
        )

    # Compare Line Items against PO
    po_items = {item.get("item_code", item.get("description", "")): item for item in (po.line_items or [])}
    grn_items = {item.get("item_code", item.get("description", "")): item for item in (grn.line_items or [])} if grn else {}

    for inv_line in (inv.line_items or []):
        key = inv_line.get("item_code", inv_line.get("description", ""))
        inv_qty = float(inv_line.get("qty", 1.0))
        inv_price = float(inv_line.get("unit_price", 0.0))

        po_match = po_items.get(key, {})
        po_qty = float(po_match.get("qty", 0.0))
        po_price = float(po_match.get("unit_price", 0.0))

        grn_match = grn_items.get(key, {})
        grn_qty = float(grn_match.get("received_qty", grn_match.get("accepted_qty", 0.0)))

        line_disc: list[str] = []

        if po_price > 0:
            unit_diff_pct = abs(inv_price - po_price) / po_price * 100.0
            if unit_diff_pct > price_tolerance_pct:
                line_disc.append(f"Price variance: Invoice=${inv_price} vs PO=${po_price} ({unit_diff_pct:.1f}%)")

        if grn:
            if inv_qty > grn_qty:
                line_disc.append(f"Quantity variance: Invoiced={inv_qty} vs Warehouse Received={grn_qty}")
        elif po_qty > 0 and inv_qty > po_qty:
            line_disc.append(f"Quantity exceeds PO: Invoiced={inv_qty} vs PO ordered={po_qty}")

        discrepancies.extend(line_disc)
        line_comparisons.append({
            "item": key,
            "inv_qty": inv_qty,
            "po_qty": po_qty,
            "grn_qty": grn_qty if grn else None,
            "inv_price": inv_price,
            "po_price": po_price,
            "variances": line_disc,
            "matched": len(line_disc) == 0,
        })

    # Determine Final Status
    match_type = "3way" if grn else "2way"

    if any("Price variance" in d or "exceeds PO" in d for d in discrepancies):
        inv.matching_status = "price_variance"
    elif any("Quantity variance" in d for d in discrepancies):
        inv.matching_status = "quantity_variance"
    elif not grn and inv.grn_number:
        inv.matching_status = "missing_grn"
    elif len(discrepancies) == 0:
        inv.matching_status = "matched_3way" if grn else "matched_2way"
    else:
        inv.matching_status = "discrepancy"

    notes = f"{match_type.upper()} Matching Result: {inv.matching_status.replace('_', ' ').title()}."
    if discrepancies:
        notes += " Discrepancies: " + "; ".join(discrepancies)
    inv.matching_notes = notes

    db.commit()
    db.refresh(inv)

    return {
        "invoice_id": inv.id,
        "status": inv.matching_status,
        "match_type": match_type,
        "notes": inv.matching_notes,
        "discrepancies": discrepancies,
        "line_comparisons": line_comparisons,
        "po_number": po.po_number if po else None,
        "grn_number": grn.grn_number if grn else None,
    }
