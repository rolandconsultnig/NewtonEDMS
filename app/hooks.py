"""Post-create / post-process hooks: workflow triggers and automation rules."""
from __future__ import annotations

import logging

from sqlalchemy.orm import Session

from app.models import Document, WorkflowTrigger

logger = logging.getLogger("newtonedms.hooks")


def after_document_create(db: Session, doc: Document) -> None:
    try:
        _fire_triggers(db, doc, "create")
    except Exception:
        logger.exception("workflow trigger failed for document %s", doc.id)
    try:
        from app.rules_engine import fire

        fire(db, "document_created", doc, {"event": "document_created"})
    except Exception:
        logger.exception("automation rules failed for document %s", doc.id)


def after_document_processed(db: Session, doc: Document) -> None:
    try:
        from app.rules_engine import fire

        fire(db, "document_processed", doc, {"event": "document_processed"})
    except Exception:
        logger.exception("processed rules failed for document %s", doc.id)


def _fire_triggers(db: Session, doc: Document, event: str) -> None:
    rows = (
        db.query(WorkflowTrigger)
        .filter(WorkflowTrigger.folder_id == doc.folder_id)
        .filter(WorkflowTrigger.event.in_((event, "upload", "*")))
        .all()
    )
    if not rows:
        return
    from app.routers.workflow import start_workflow_internal

    for row in rows:
        try:
            start_workflow_internal(db, doc.id, row.template_id, created_by=doc.created_by)
        except Exception:
            logger.warning("trigger %s skipped", row.id, exc_info=True)
