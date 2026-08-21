"""Intelligent OCR and Line-Item Extraction Parser for Invoices and Receipts."""
from __future__ import annotations

import re
from datetime import datetime
from typing import Any


def parse_invoice_ocr_text(text: str) -> dict[str, Any]:
    """Extract structured header fields and line-item tables from OCR text."""
    data: dict[str, Any] = {
        "invoice_number": "",
        "vendor_name": "",
        "vendor_tax_id": "",
        "po_number": "",
        "invoice_date": None,
        "due_date": None,
        "subtotal": 0.0,
        "tax_amount": 0.0,
        "total_amount": 0.0,
        "currency": "USD",
        "line_items": [],
    }

    if not text:
        return data

    lines = [line.strip() for line in text.splitlines() if line.strip()]

    # 1. Invoice Number
    inv_match = re.search(
        r"(?:invoice\s*(?:no\.?|number|#)|inv\s*#?)\s*[:\-]?\s*([A-Za-z0-9\-_/]{3,30})",
        text,
        re.IGNORECASE,
    )
    if inv_match:
        data["invoice_number"] = inv_match.group(1).strip()

    # 2. Tax ID / VAT / EIN
    tax_match = re.search(
        r"(?:tax\s*id|ein|vat\s*(?:reg\.?|no\.?|#)|gstin)\s*[:\-]?\s*([A-Za-z0-9\-]{5,20})",
        text,
        re.IGNORECASE,
    )
    if tax_match:
        data["vendor_tax_id"] = tax_match.group(1).strip()

    # 3. PO Number
    po_match = re.search(
        r"(?:p\.?o\.?\s*(?:no\.?|number|#)|purchase\s*order\s*#?)\s*[:\-]?\s*([A-Za-z0-9\-_/]{3,30})",
        text,
        re.IGNORECASE,
    )
    if po_match:
        data["po_number"] = po_match.group(1).strip()

    # 4. Dates
    date_patterns = [
        r"(?:invoice\s*date|date|dated)\s*[:\-]?\s*(\d{4}[-/]\d{1,2}[-/]\d{1,2}|\d{1,2}[-/]\d{1,2}[-/]\d{2,4})",
        r"(?:due\s*date|payment\s*due)\s*[:\-]?\s*(\d{4}[-/]\d{1,2}[-/]\d{1,2}|\d{1,2}[-/]\d{1,2}[-/]\d{2,4})",
    ]
    inv_date_m = re.search(date_patterns[0], text, re.IGNORECASE)
    if inv_date_m:
        data["invoice_date"] = inv_date_m.group(1).strip()

    due_date_m = re.search(date_patterns[1], text, re.IGNORECASE)
    if due_date_m:
        data["due_date"] = due_date_m.group(1).strip()

    # 5. Amounts
    total_match = re.search(
        r"\b(?:total\s*(?:amount|due)?|grand\s*total|balance\s*due|amount\s*due)\s*[:\-]?\s*[\$€£]?\s*([\d,]+\.\d{2})",
        text,
        re.IGNORECASE,
    )
    if total_match:
        data["total_amount"] = float(total_match.group(1).replace(",", ""))

    subtotal_match = re.search(
        r"\b(?:sub\s*total|subtotal|net\s*amount)\s*[:\-]?\s*[\$€£]?\s*([\d,]+\.\d{2})",
        text,
        re.IGNORECASE,
    )
    if subtotal_match:
        data["subtotal"] = float(subtotal_match.group(1).replace(",", ""))

    tax_match_amt = re.search(
        r"\b(?:tax|vat|sales\s*tax|gst)\s*[:\-]?\s*[\$€£]?\s*([\d,]+\.\d{2})",
        text,
        re.IGNORECASE,
    )
    if tax_match_amt:
        data["tax_amount"] = float(tax_match_amt.group(1).replace(",", ""))

    # 6. Currency
    if "€" in text or "EUR" in text:
        data["currency"] = "EUR"
    elif "£" in text or "GBP" in text:
        data["currency"] = "GBP"
    elif "CAD" in text:
        data["currency"] = "CAD"
    else:
        data["currency"] = "USD"

    # 7. Line Items (Tabular regex: Description ... Qty ... Unit Price ... Total)
    line_item_pattern = re.compile(
        r"^(?P<desc>[A-Za-z0-9\s\-_\.,#]{3,40})\s+(?P<qty>\d+(?:\.\d+)?)\s+[\$€£]?(?P<price>\d+(?:\.\d{2})?)\s+[\$€£]?(?P<total>\d+(?:\.\d{2})?)$"
    )
    for line in lines:
        m = line_item_pattern.match(line)
        if m:
            desc = m.group("desc").strip()
            # Ignore table header rows
            if desc.lower() in ("description", "item", "product", "subtotal", "total", "tax"):
                continue
            data["line_items"].append({
                "item_code": desc[:20],
                "description": desc,
                "qty": float(m.group("qty")),
                "unit_price": float(m.group("price")),
                "total": float(m.group("total")),
            })

    # If subtotal missing, calculate from lines
    if data["subtotal"] == 0.0 and data["line_items"]:
        data["subtotal"] = sum(item["total"] for item in data["line_items"])
        if data["total_amount"] == 0.0:
            data["total_amount"] = data["subtotal"] + data["tax_amount"]

    # Vendor Name heuristic (often top line of document if not a header)
    for l in lines[:5]:
        if not any(k in l.lower() for k in ("invoice", "tax", "date", "bill to", "ship to", "page")):
            data["vendor_name"] = l
            break

    return data
