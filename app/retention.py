"""Apply retention policies, skipping documents on legal hold."""
from __future__ import annotations

import logging
import shutil
from datetime import timedelta

from sqlalchemy.orm import Session

from app.compliance import is_held
from app.database import now
from app.indexing import remove_document
from app.models import Document, RetentionPolicy
from app.purge import purge_document_children
from app.storage import doc_storage_dir

logger = logging.getLogger("newtonedms.retention")


def apply_all(db: Session) -> dict:
    affected = 0
    failed = 0
    skipped = 0
    for policy in db.query(RetentionPolicy).all():
        cutoff = now() - timedelta(days=(policy.years or 0) * 365)
        q = db.query(Document).filter(Document.created_at < cutoff, Document.deleted_at.is_(None))
        if policy.folder_id:
            q = q.filter(Document.folder_id == policy.folder_id)
        for d in q.all():
            if is_held(db, d):
                skipped += 1
                continue
            if policy.action == "archive":
                d.status = "archived"
                d.updated_at = now()
                affected += 1
            elif policy.action == "delete":
                try:
                    doc_id = d.id
                    purge_document_children(db, doc_id)
                    remove_document(doc_id)
                    db.delete(d)
                    db.commit()
                    ddir = doc_storage_dir(doc_id)
                    if ddir.exists():
                        shutil.rmtree(ddir, ignore_errors=True)
                    affected += 1
                except Exception:
                    logger.exception("retention delete failed for %s", d.id)
                    db.rollback()
                    failed += 1
    db.commit()
    return {"affected": affected, "failed": failed, "skipped_holds": skipped}
