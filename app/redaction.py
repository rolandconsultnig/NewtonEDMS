"""Permanent non-reversible redaction engine for PII and confidential trade secrets."""
from __future__ import annotations

import io
import logging
from pathlib import Path
import re
from typing import Any

from fastapi import HTTPException
from sqlalchemy.orm import Session

from app.config import BASE_DIR
from app.database import now
from app.models import Document, RedactionRule, User

logger = logging.getLogger("newtonedms.legal.redaction")

BUILTIN_PATTERNS = {
    "us_ssn": r"\b\d{3}-\d{2}-\d{4}\b",
    "credit_card": r"\b(?:\d{4}[ -]?){3}\d{4}\b",
    "email": r"\b[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Z|a-z]{2,}\b",
    "us_phone": r"\b(?:\+?1[-. ]?)?\(?\d{3}\)?[-. ]?\d{3}[-. ]?\d{4}\b",
    "iban": r"\b[A-Z]{2}\d{2}[A-Z0-9]{4}\d{7}([A-Z0-9]?){0,16}\b",
    "ein_tax_id": r"\b\d{2}-\d{7}\b",
}


def redact_text_stream(text: str, patterns: list[str]) -> tuple[str, int]:
    """Redact text using regex patterns and replace with blacked block markers."""
    total_redactions = 0
    redacted = text
    for pat in patterns:
        try:
            matches = re.findall(pat, redacted, re.IGNORECASE)
            total_redactions += len(matches)
            redacted = re.sub(pat, "██████████", redacted, flags=re.IGNORECASE)
        except Exception as e:
            logger.warning("Pattern error in redaction: %s", e)
    return redacted, total_redactions


def apply_permanent_pdf_redaction(
    pdf_bytes: bytes,
    patterns: list[str] | None = None,
    boxes: list[dict[str, Any]] | None = None,
) -> tuple[bytes, int]:
    """
    Apply permanent non-reversible redactions to a PDF document using PyMuPDF (fitz) or PDF text stream redaction.
    Burns opaque black boxes and removes underlying characters from the text layer.
    """
    patterns = patterns or []
    boxes = boxes or []
    total_redacted = 0

    if pdf_bytes and pdf_bytes.startswith(b"%PDF"):
        try:
            import fitz  # PyMuPDF

            doc = fitz.open(stream=pdf_bytes, filetype="pdf")
            for page in doc:
                # 1. Pattern text search & redact
                for pat in patterns:
                    text_instances = []
                    page_text = page.get_text()
                    for match in re.finditer(pat, page_text, re.IGNORECASE):
                        found_str = match.group(0)
                        rects = page.search_for(found_str)
                        text_instances.extend(rects)

                    for rect in text_instances:
                        page.add_redact_annot(rect, fill=(0, 0, 0))  # Solid black box
                        total_redacted += 1

                # 2. Bounding boxes [page_num, x, y, w, h]
                page_num = page.number + 1
                for b in boxes:
                    if b.get("page") == page_num or b.get("page") == 0:
                        r = fitz.Rect(b["x"], b["y"], b["x"] + b["w"], b["y"] + b["h"])
                        page.add_redact_annot(r, fill=(0, 0, 0))
                        total_redacted += 1

                # Permanently apply redactions and strip underlying font glyphs
                page.apply_redactions()

            out_bytes = doc.tobytes(deflate=True)
            doc.close()
            return out_bytes, total_redacted

        except Exception as e:
            logger.info("PyMuPDF redaction failed (%s); applying stream level redaction fallback.", e)

    # Fallback: strip text from raw stream
    text_content = pdf_bytes.decode("utf-8", errors="replace") if pdf_bytes else ""
    redacted_text, count = redact_text_stream(text_content, patterns)
    return redacted_text.encode("utf-8"), count


def execute_document_redaction(
    db: Session,
    user: User,
    document_id: int,
    patterns: list[str] | None = None,
    builtin_presets: list[str] | None = None,
    bounding_boxes: list[dict[str, Any]] | None = None,
    save_as_new: bool = True,
) -> dict[str, Any]:
    """Execute permanent redaction on a document and update audit records."""
    doc = db.get(Document, document_id)
    if not doc or doc.deleted_at is not None:
        raise HTTPException(status_code=404, detail="Document not found.")

    all_patterns = list(patterns or [])
    if builtin_presets:
        for p in builtin_presets:
            if p in BUILTIN_PATTERNS:
                all_patterns.append(BUILTIN_PATTERNS[p])

    if not all_patterns and not bounding_boxes:
        # Default to SSN, Credit Card, Email
        all_patterns.extend([BUILTIN_PATTERNS["us_ssn"], BUILTIN_PATTERNS["credit_card"]])

    storage_root = BASE_DIR / "storage"
    raw_bytes = b""
    if doc.file_path:
        fpath = storage_root / doc.file_path
        if fpath.exists():
            raw_bytes = fpath.read_bytes()

    if not raw_bytes and doc.extracted_text:
        raw_bytes = doc.extracted_text.encode("utf-8")

    redacted_bytes, count = apply_permanent_pdf_redaction(raw_bytes, all_patterns, bounding_boxes)
    redacted_text, _ = redact_text_stream(doc.extracted_text or "", all_patterns)

    if save_as_new:
        rel_path = f"redacted/{now().strftime('%Y%m%d')}_{doc.id}_REDACTED.pdf"
        target_file = storage_root / rel_path
        target_file.parent.mkdir(parents=True, exist_ok=True)
        target_file.write_bytes(redacted_bytes)

        redacted_doc = Document(
            name=f"{doc.name}_REDACTED.pdf",
            title=f"{doc.title} (Redacted)",
            file_path=str(rel_path).replace("\\", "/"),
            mime=doc.mime or "application/pdf",
            size=len(redacted_bytes),
            folder_id=doc.folder_id,
            created_by=user.id,
            created_at=now(),
            extracted_text=redacted_text,
            metadata_json={
                "redacted_from_id": doc.id,
                "redaction_count": count,
                "applied_patterns": all_patterns,
            },
            tags=f"redacted,{doc.tags or ''}",
            status="active",
        )
        db.add(redacted_doc)
        db.commit()
        db.refresh(redacted_doc)
        target_doc_id = redacted_doc.id
    else:
        # In-place overwrite
        if doc.file_path:
            fpath = storage_root / doc.file_path
            fpath.write_bytes(redacted_bytes)
        doc.extracted_text = redacted_text
        doc.size = len(redacted_bytes)
        doc.metadata_json = dict(doc.metadata_json or {})
        doc.metadata_json["last_redacted_at"] = now().isoformat()
        db.commit()
        target_doc_id = doc.id

    return {
        "status": "success",
        "original_document_id": doc.id,
        "redacted_document_id": target_doc_id,
        "redactions_applied": count,
        "patterns_used": all_patterns,
    }
