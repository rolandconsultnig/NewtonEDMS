"""Intelligent Clinical Document Processing (IDP) for Doctor Notes, Discharge Summaries & Lab Reports."""
from __future__ import annotations

import re
from typing import Any


def parse_clinical_chart_text(text: str) -> dict[str, Any]:
    """
    Extract structured clinical fields from doctor's progress notes, discharge summaries, or faxed lab orders.
    """
    data: dict[str, Any] = {
        "patient_name": "",
        "mrn": "",
        "attending_physician": "",
        "vital_signs": {
            "blood_pressure": "",
            "heart_rate": "",
            "temperature": "",
            "spo2": "",
            "respiratory_rate": "",
        },
        "chief_complaint": "",
        "icd10_diagnoses": [],
        "allergies": [],
        "medications": [],
    }

    if not text:
        return data

    # 1. Patient & MRN
    pat_m = re.search(r"(?:patient\s*(?:name)?|pt\s*name)\s*[:\-]?\s*([^\r\n,]{3,35})", text, re.IGNORECASE)
    if pat_m:
        data["patient_name"] = pat_m.group(1).strip()

    mrn_m = re.search(r"(?:mrn|medical\s*record\s*#?)\s*[:\-]?\s*([A-Za-z0-9\-_/]{4,20})", text, re.IGNORECASE)
    if mrn_m:
        data["mrn"] = mrn_m.group(1).strip()

    # 2. Attending Physician
    phy_m = re.search(r"(?:attending\s*(?:physician|dr\.?)|provider|dr\.)\s*[:\-]?\s*([^\r\n,]{3,35})", text, re.IGNORECASE)
    if phy_m:
        data["attending_physician"] = phy_m.group(1).strip()

    # 3. Vital Signs
    bp_m = re.search(r"\b(?:bp|blood\s*pressure)\s*[:\-]?\s*(\d{2,3}/\d{2,3})\b", text, re.IGNORECASE)
    if bp_m:
        data["vital_signs"]["blood_pressure"] = bp_m.group(1)

    hr_m = re.search(r"\b(?:hr|pulse|heart\s*rate)\s*[:\-]?\s*(\d{2,3})\s*(?:bpm)?\b", text, re.IGNORECASE)
    if hr_m:
        data["vital_signs"]["heart_rate"] = f"{hr_m.group(1)} bpm"

    temp_m = re.search(r"\b(?:temp|temperature)\s*[:\-]?\s*(\d{2,3}(?:\.\d)?)\s*(?:[CFcf]|deg)?\b", text, re.IGNORECASE)
    if temp_m:
        data["vital_signs"]["temperature"] = f"{temp_m.group(1)} F"

    spo2_m = re.search(r"\b(?:spo2|o2\s*sat|pulse\s*ox)\s*[:\-]?\s*(\d{2,3})%?\b", text, re.IGNORECASE)
    if spo2_m:
        data["vital_signs"]["spo2"] = f"{spo2_m.group(1)}%"

    # 4. Chief Complaint
    cc_m = re.search(r"(?:chief\s*complaint|reason\s*for\s*admission|cc)\s*[:\-]?\s*([^\r\n]{5,80})", text, re.IGNORECASE)
    if cc_m:
        data["chief_complaint"] = cc_m.group(1).strip()

    # 5. ICD-10 Diagnoses
    icd_codes = re.findall(r"\b([A-TV-Z][0-9][0-9AB]\.[0-9A-KXZ]{1,4})\b", text)
    if icd_codes:
        data["icd10_diagnoses"] = list(set(icd_codes))

    # 6. Allergies
    allg_m = re.search(r"(?:allergies|nka|nkda)\s*[:\-]?\s*([^\r\n]{3,60})", text, re.IGNORECASE)
    if allg_m:
        raw_allg = allg_m.group(1).strip()
        data["allergies"] = [a.strip() for a in raw_allg.split(",") if a.strip()]

    # 7. Medications / Rx
    rx_m = re.findall(r"(?:rx|medication|meds?)\s*[:\-]?\s*([^\r\n]{5,50})", text, re.IGNORECASE)
    if rx_m:
        data["medications"] = [r.strip() for r in rx_m]

    return data
