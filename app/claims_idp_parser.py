"""Intelligent Document Processing (IDP) for Insurance Claims (Police Reports, Medical, Estimates)."""
from __future__ import annotations

import re
from typing import Any


def parse_police_report(text: str) -> dict[str, Any]:
    """Extract structured accident details from Police Traffic Crash / Incident Reports."""
    data: dict[str, Any] = {
        "doc_type": "police_report",
        "report_number": "",
        "department": "",
        "officer_name": "",
        "badge_number": "",
        "incident_date": "",
        "location": "",
        "fault_determination": "",
        "citations": [],
        "vehicles_involved": [],
    }
    if not text:
        return data

    rep_m = re.search(r"(?:report\s*(?:no\.?|#|number)|incident\s*#?)\s*[:\-]?\s*([A-Za-z0-9\-_/]{4,25})", text, re.IGNORECASE)
    if rep_m:
        data["report_number"] = rep_m.group(1).strip()

    dept_m = re.search(r"(?:police\s*dept|police\s*department|sheriff|highway\s*patrol|state\s*police)\s*[:\-]?\s*([^\r\n]{3,40})", text, re.IGNORECASE)
    if dept_m:
        data["department"] = dept_m.group(0).strip()

    officer_m = re.search(r"(?:investigating\s*officer|officer\s*name|officer)\s*[:\-]?\s*([^\r\n,]{3,30})", text, re.IGNORECASE)
    if officer_m:
        data["officer_name"] = officer_m.group(1).strip()

    badge_m = re.search(r"(?:badge\s*(?:#|no\.?)|id\s*#)\s*[:\-]?\s*([A-Za-z0-9\-]{2,15})", text, re.IGNORECASE)
    if badge_m:
        data["badge_number"] = badge_m.group(1).strip()

    date_m = re.search(r"(?:date\s*of\s*(?:crash|accident|incident)|incident\s*date)\s*[:\-]?\s*(\d{4}[-/]\d{1,2}[-/]\d{1,2}|\d{1,2}[-/]\d{1,2}[-/]\d{2,4})", text, re.IGNORECASE)
    if date_m:
        data["incident_date"] = date_m.group(1).strip()

    # Fault determination heuristic
    if re.search(r"driver\s*(?:1|2)\s*at\s*fault|contributing\s*factors|cause\s*of\s*crash", text, re.IGNORECASE):
        fault_m = re.search(r"(?:at\s*fault|cause\s*of\s*crash)\s*[:\-]?\s*([^\r\n]{5,60})", text, re.IGNORECASE)
        if fault_m:
            data["fault_determination"] = fault_m.group(1).strip()

    # Citations
    citation_m = re.findall(r"(?:citation|charge|violation)\s*[:\-]?\s*([^\r\n]{5,40})", text, re.IGNORECASE)
    if citation_m:
        data["citations"] = [c.strip() for c in citation_m]

    return data


def parse_medical_record(text: str) -> dict[str, Any]:
    """Extract medical billing, diagnosis ICD codes, and treating provider details."""
    data: dict[str, Any] = {
        "doc_type": "medical_record",
        "provider_name": "",
        "patient_name": "",
        "service_date": "",
        "icd_codes": [],
        "total_billed": 0.0,
        "treatment_summary": "",
    }
    if not text:
        return data

    prov_m = re.search(r"(?:hospital|clinic|medical\s*center|provider|physician)\s*[:\-]?\s*([^\r\n]{3,40})", text, re.IGNORECASE)
    if prov_m:
        data["provider_name"] = prov_m.group(1).strip()

    pat_m = re.search(r"(?:patient\s*name|patient)\s*[:\-]?\s*([^\r\n,]{3,30})", text, re.IGNORECASE)
    if pat_m:
        data["patient_name"] = pat_m.group(1).strip()

    # ICD-10 Diagnosis Codes (e.g. S06.0X0A, M54.5)
    icd_m = re.findall(r"\b([A-TV-Z][0-9][0-9AB]\.[0-9A-KXZ]{1,4})\b", text)
    if icd_m:
        data["icd_codes"] = list(set(icd_m))

    # Total Billed
    billed_m = re.search(r"\b(?:total\s*(?:charges|billed|amount)|amount\s*due)\s*[:\-]?\s*[\$€£]?\s*([\d,]+\.\d{2})", text, re.IGNORECASE)
    if billed_m:
        data["total_billed"] = float(billed_m.group(1).replace(",", ""))

    return data


def parse_repair_estimate(text: str) -> dict[str, Any]:
    """Extract vehicle repair estimate with labor, parts cost, and vehicle VIN."""
    data: dict[str, Any] = {
        "doc_type": "repair_estimate",
        "repair_shop": "",
        "vin": "",
        "parts_total": 0.0,
        "labor_total": 0.0,
        "total_estimate": 0.0,
        "labor_hours": 0.0,
    }
    if not text:
        return data

    shop_m = re.search(r"(?:body\s*shop|repair\s*facility|shop\s*name)\s*[:\-]?\s*([^\r\n]{3,40})", text, re.IGNORECASE)
    if shop_m:
        data["repair_shop"] = shop_m.group(1).strip()

    # VIN (17 alphanumeric chars)
    vin_m = re.search(r"\b([A-HJ-NPR-Z0-9]{17})\b", text)
    if vin_m:
        data["vin"] = vin_m.group(1).strip()

    parts_m = re.search(r"\b(?:parts\s*(?:total|subtotal)?)\s*[:\-]?\s*[\$€£]?\s*([\d,]+\.\d{2})", text, re.IGNORECASE)
    if parts_m:
        data["parts_total"] = float(parts_m.group(1).replace(",", ""))

    labor_m = re.search(r"\b(?:labor\s*(?:total|subtotal)?)\s*[:\-]?\s*[\$€£]?\s*([\d,]+\.\d{2})", text, re.IGNORECASE)
    if labor_m:
        data["labor_total"] = float(labor_m.group(1).replace(",", ""))

    total_m = re.search(r"\b(?:net\s*total|total\s*estimate|grand\s*total|total\s*amount)\s*[:\-]?\s*[\$€£]?\s*([\d,]+\.\d{2})", text, re.IGNORECASE)
    if total_m:
        data["total_estimate"] = float(total_m.group(1).replace(",", ""))

    hours_m = re.search(r"\b(?:labor\s*hours|total\s*hours)\s*[:\-]?\s*([\d\.]+)", text, re.IGNORECASE)
    if hours_m:
        data["labor_hours"] = float(hours_m.group(1))

    return data
