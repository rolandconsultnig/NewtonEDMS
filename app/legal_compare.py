"""Document comparison and legal redline diff engine."""
from __future__ import annotations

import difflib
import html
import logging
import re
from typing import Any

from fastapi import HTTPException
from sqlalchemy.orm import Session

from app.models import Document, DocumentVersion, User

logger = logging.getLogger("newtonedms.legal.compare")


def compute_legal_redline(text_orig: str, text_revised: str) -> dict[str, Any]:
    """
    Produce a legal redline comparison between original and revised text.
    Returns inline HTML, side-by-side blocks, and statistics.
    """
    words_orig = re.findall(r"\S+|\s+", text_orig)
    words_revised = re.findall(r"\S+|\s+", text_revised)

    matcher = difflib.SequenceMatcher(None, words_orig, words_revised)
    inline_parts = []
    side_by_side = []

    insertions = 0
    deletions = 0
    modifications = 0

    for tag, i1, i2, j1, j2 in matcher.get_opcodes():
        orig_chunk = "".join(words_orig[i1:i2])
        rev_chunk = "".join(words_revised[j1:j2])

        if tag == "equal":
            inline_parts.append(html.escape(orig_chunk))
            side_by_side.append({
                "type": "equal",
                "left": orig_chunk,
                "right": rev_chunk,
            })
        elif tag == "delete":
            deletions += len([w for w in words_orig[i1:i2] if w.strip()])
            inline_parts.append(f'<del class="legal-del text-red-600 bg-red-100 dark:bg-red-950/50 line-through px-1 rounded">{html.escape(orig_chunk)}</del>')
            side_by_side.append({
                "type": "delete",
                "left": orig_chunk,
                "right": "",
            })
        elif tag == "insert":
            insertions += len([w for w in words_revised[j1:j2] if w.strip()])
            inline_parts.append(f'<ins class="legal-ins text-emerald-700 dark:text-emerald-400 bg-emerald-100 dark:bg-emerald-950/50 underline px-1 rounded font-medium">{html.escape(rev_chunk)}</ins>')
            side_by_side.append({
                "type": "insert",
                "left": "",
                "right": rev_chunk,
            })
        elif tag == "replace":
            del_cnt = len([w for w in words_orig[i1:i2] if w.strip()])
            ins_cnt = len([w for w in words_revised[j1:j2] if w.strip()])
            deletions += del_cnt
            insertions += ins_cnt
            modifications += max(del_cnt, ins_cnt)
            inline_parts.append(f'<del class="legal-del text-red-600 bg-red-100 dark:bg-red-950/50 line-through px-1 rounded">{html.escape(orig_chunk)}</del>')
            inline_parts.append(f'<ins class="legal-ins text-emerald-700 dark:text-emerald-400 bg-emerald-100 dark:bg-emerald-950/50 underline px-1 rounded font-medium">{html.escape(rev_chunk)}</ins>')
            side_by_side.append({
                "type": "replace",
                "left": orig_chunk,
                "right": rev_chunk,
            })

    similarity_ratio = round(matcher.ratio() * 100, 1)

    return {
        "similarity_score": similarity_ratio,
        "insertions_count": insertions,
        "deletions_count": deletions,
        "modifications_count": modifications,
        "inline_html": "".join(inline_parts),
        "side_by_side": side_by_side,
    }


def compare_documents(
    db: Session,
    user: User,
    doc_id_a: int,
    doc_id_b: int | None = None,
    version_num_a: int | None = None,
    version_num_b: int | None = None,
) -> dict[str, Any]:
    """Compare two documents or two versions of a document and return legal redline diff."""
    doc_a = db.get(Document, doc_id_a)
    if not doc_a or doc_a.deleted_at is not None:
        raise HTTPException(status_code=404, detail="Original document not found.")

    text_a = doc_a.extracted_text or doc_a.title or ""
    label_a = f"{doc_a.title} (Current)"

    # Version A
    if version_num_a:
        ver_a = db.query(DocumentVersion).filter(
            DocumentVersion.document_id == doc_id_a,
            DocumentVersion.version_number == version_num_a,
        ).first()
        if ver_a and ver_a.comment:
            text_a = ver_a.comment
            label_a = f"{doc_a.title} (v{version_num_a})"

    # Document B
    if doc_id_b:
        doc_b = db.get(Document, doc_id_b)
        if not doc_b or doc_b.deleted_at is not None:
            raise HTTPException(status_code=404, detail="Revised document not found.")
        text_b = doc_b.extracted_text or doc_b.title or ""
        label_b = f"{doc_b.title} (Current)"
    elif version_num_b:
        ver_b = db.query(DocumentVersion).filter(
            DocumentVersion.document_id == doc_id_a,
            DocumentVersion.version_number == version_num_b,
        ).first()
        if not ver_b:
            raise HTTPException(status_code=404, detail=f"Version {version_num_b} not found.")
        text_b = ver_b.comment or ""
        label_b = f"{doc_a.title} (v{version_num_b})"
    else:
        text_b = text_a
        label_b = label_a

    redline_result = compute_legal_redline(text_a, text_b)
    return {
        "status": "success",
        "doc_a": {"id": doc_id_a, "label": label_a},
        "doc_b": {"id": doc_id_b or doc_id_a, "label": label_b},
        **redline_result,
    }
