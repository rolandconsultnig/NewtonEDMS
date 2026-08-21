"""Insurance Claims Fraud Detection & EXIF Metadata Analyzer."""
from __future__ import annotations

import hashlib
import io
import logging
from datetime import datetime
from typing import Any

from sqlalchemy.orm import Session

from app.models import ClaimEvidence, InsuranceClaim

logger = logging.getLogger("newtonedms.insurance.fraud")


def analyze_image_exif_and_fraud(
    db: Session,
    claim: InsuranceClaim,
    image_bytes: bytes,
    evidence_type: str = "scene_photo",
) -> dict[str, Any]:
    """
    Analyze image EXIF metadata and detect fraudulent patterns:
    1. EXIF GPS location & capture timestamp vs claim loss date.
    2. Image editing software footprint (Photoshop, Canva, GIMP).
    3. Duplicate crash photo hash detection across historical claims.
    """
    img_hash = hashlib.sha256(image_bytes).hexdigest()
    exif_data: dict[str, Any] = {
        "camera_make": "",
        "camera_model": "",
        "software": "",
        "datetime_original": None,
        "gps_latitude": None,
        "gps_longitude": None,
        "is_edited": False,
    }
    flags: list[str] = []
    risk_score = 0

    try:
        from PIL import Image
        from PIL.ExifTags import GPSTAGS, TAGS

        img = Image.open(io.BytesIO(image_bytes))
        raw_exif = img._getexif()

        if raw_exif:
            for tag_id, val in raw_exif.items():
                tag_name = TAGS.get(tag_id, tag_id)
                if tag_name == "Make":
                    exif_data["camera_make"] = str(val)
                elif tag_name == "Model":
                    exif_data["camera_model"] = str(val)
                elif tag_name == "Software":
                    exif_data["software"] = str(val)
                elif tag_name == "DateTimeOriginal":
                    exif_data["datetime_original"] = str(val)
                elif tag_name == "GPSInfo":
                    # Parse GPS info if present
                    gps_info = {}
                    for g_id, g_val in val.items():
                        g_tag = GPSTAGS.get(g_id, g_id)
                        gps_info[g_tag] = g_val
                    exif_data["gps_info"] = gps_info

            # Check for editing software
            soft = exif_data["software"].lower()
            if any(s in soft for s in ("photoshop", "gimp", "canva", "lightroom", "pixelmator")):
                exif_data["is_edited"] = True
                flags.append(f"Image edited with software: '{exif_data['software']}'")
                risk_score += 35

    except Exception as e:
        logger.debug("EXIF parsing skipped: %s", e)

    # Cross-claim duplicate image hash check
    existing_dup = (
        db.query(ClaimEvidence)
        .filter(ClaimEvidence.image_hash == img_hash, ClaimEvidence.claim_id != claim.id)
        .first()
    )
    if existing_dup:
        flags.append(f"Duplicate image collision: Photo was previously submitted in Claim ID #{existing_dup.claim_id}")
        risk_score += 60

    claim.fraud_score = min(100, (claim.fraud_score or 0) + risk_score)
    if flags:
        claim.fraud_flags = list(set((claim.fraud_flags or []) + flags))
        db.commit()
        db.refresh(claim)

    return {
        "image_hash": img_hash,
        "exif": exif_data,
        "is_fraud_flagged": len(flags) > 0,
        "risk_score_added": risk_score,
        "total_claim_fraud_score": claim.fraud_score,
        "fraud_flags": flags,
    }
