"""Batch Document Capture and Barcode / Separator Sheet Indexing Engine."""
from __future__ import annotations

import logging
import re
from pathlib import Path
from typing import Any

from sqlalchemy.orm import Session

from app.database import BASE_DIR, now
from app.models import Document, InvoiceRecord, User

logger = logging.getLogger("newtonedms.accounting.barcode")


def split_batch_by_barcode(
    db: Session,
    user: User,
    pdf_bytes: bytes,
    folder_id: int,
    batch_name: str = "Batch_Scan",
    barcode_pattern: str = r"(?:BARCODE|QR|SEP)[:\s\-]+([A-Za-z0-9\-_]+)",
) -> list[dict[str, Any]]:
    """
    Split multi-page scanned PDF batches at barcode separator pages or QR code headers.
    Creates indexed Document records for each split sub-file.
    """
    results: list[dict[str, Any]] = []

    try:
        import fitz  # PyMuPDF

        doc = fitz.open(stream=pdf_bytes, filetype="pdf")
        total_pages = len(doc)
        current_split_doc = fitz.open()
        current_barcode = "DOCUMENT-1"
        split_index = 1
        storage_root = BASE_DIR / "storage"

        for page_idx in range(total_pages):
            page = doc[page_idx]
            text = page.get_text()

            # Check if this page contains a barcode / QR separator
            match = re.search(barcode_pattern, text, re.IGNORECASE)
            is_separator = match is not None or "[PAGE_SPLIT]" in text or "BATCH-SEPARATOR" in text

            if is_separator and len(current_split_doc) > 0:
                # Save current accumulated document
                sub_bytes = current_split_doc.tobytes(deflate=True)
                doc_title = f"{batch_name}_Part{split_index}_{current_barcode}"
                rel_path = f"batches/{now().strftime('%Y%m%d')}_{split_index}_{current_barcode}.pdf"
                target = storage_root / rel_path
                target.parent.mkdir(parents=True, exist_ok=True)
                target.write_bytes(sub_bytes)

                new_doc = Document(
                    name=f"{doc_title}.pdf",
                    title=doc_title,
                    file_path=str(rel_path).replace("\\", "/"),
                    mime="application/pdf",
                    size=len(sub_bytes),
                    folder_id=folder_id,
                    created_by=user.id,
                    created_at=now(),
                    metadata_json={"barcode": current_barcode, "split_index": split_index, "batch": batch_name},
                    tags=f"accounting,batch-scan,{current_barcode}",
                    status="active",
                )
                db.add(new_doc)
                db.commit()
                db.refresh(new_doc)

                results.append({
                    "document_id": new_doc.id,
                    "title": new_doc.title,
                    "barcode": current_barcode,
                    "page_count": len(current_split_doc),
                })

                # Reset for next split
                current_split_doc.close()
                current_split_doc = fitz.open()
                split_index += 1
                if match:
                    current_barcode = match.group(1).strip()
            else:
                if match:
                    current_barcode = match.group(1).strip()
                current_split_doc.insert_pdf(doc, from_page=page_idx, to_page=page_idx)

        # Save remaining pages
        if len(current_split_doc) > 0:
            sub_bytes = current_split_doc.tobytes(deflate=True)
            doc_title = f"{batch_name}_Part{split_index}_{current_barcode}"
            rel_path = f"batches/{now().strftime('%Y%m%d')}_{split_index}_{current_barcode}.pdf"
            target = storage_root / rel_path
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(sub_bytes)

            new_doc = Document(
                name=f"{doc_title}.pdf",
                title=doc_title,
                file_path=str(rel_path).replace("\\", "/"),
                mime="application/pdf",
                size=len(sub_bytes),
                folder_id=folder_id,
                created_by=user.id,
                created_at=now(),
                metadata_json={"barcode": current_barcode, "split_index": split_index, "batch": batch_name},
                tags=f"accounting,batch-scan,{current_barcode}",
                status="active",
            )
            db.add(new_doc)
            db.commit()
            db.refresh(new_doc)

            results.append({
                "document_id": new_doc.id,
                "title": new_doc.title,
                "barcode": current_barcode,
                "page_count": len(current_split_doc),
            })
            current_split_doc.close()

        doc.close()

    except Exception as e:
        logger.warning("PyMuPDF batch split failed (%s); returning single document fallback.", e)
        # Fallback single document
        rel_path = f"batches/{now().strftime('%Y%m%d_%H%M%S')}_{batch_name}.pdf"
        target = BASE_DIR / "storage" / rel_path
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(pdf_bytes)

        fallback_doc = Document(
            name=f"{batch_name}.pdf",
            title=batch_name,
            file_path=str(rel_path).replace("\\", "/"),
            mime="application/pdf",
            size=len(pdf_bytes),
            folder_id=folder_id,
            created_by=user.id,
            created_at=now(),
            tags="accounting,batch-scan",
            status="active",
        )
        db.add(fallback_doc)
        db.commit()
        db.refresh(fallback_doc)
        results.append({
            "document_id": fallback_doc.id,
            "title": fallback_doc.title,
            "barcode": "SINGLE-BATCH",
            "page_count": 1,
        })

    return results
