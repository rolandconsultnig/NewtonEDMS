"""Delete all child rows that reference a document so FK-safe purge works."""
from __future__ import annotations

from sqlalchemy.orm import Session

from app.models import (
    ArchiveLinkEntry,
    CalendarEvent,
    CaseDocument,
    CollabOp,
    Comment,
    CustomFieldValue,
    Document,
    DocumentAttachment,
    DocumentLink,
    DocumentVersion,
    FormSubmission,
    JobLog,
    LegalHoldItem,
    ProcessingJob,
    ReadingConfirmation,
    ShareLink,
    Task,
    VectorChunk,
    WorkflowInstance,
)


def purge_document_children(db: Session, doc_id: int) -> None:
    instance_ids = [
        row[0]
        for row in db.query(WorkflowInstance.id).filter(WorkflowInstance.document_id == doc_id).all()
    ]
    if instance_ids:
        db.query(Task).filter(Task.instance_id.in_(instance_ids)).delete(synchronize_session=False)
        db.query(WorkflowInstance).filter(WorkflowInstance.id.in_(instance_ids)).delete(
            synchronize_session=False
        )
    db.query(Comment).filter(Comment.document_id == doc_id).delete(synchronize_session=False)
    db.query(ShareLink).filter(ShareLink.document_id == doc_id).delete(synchronize_session=False)
    db.query(DocumentVersion).filter(DocumentVersion.document_id == doc_id).delete(
        synchronize_session=False
    )
    db.query(DocumentAttachment).filter(DocumentAttachment.document_id == doc_id).delete(
        synchronize_session=False
    )
    db.query(CustomFieldValue).filter(CustomFieldValue.document_id == doc_id).delete(
        synchronize_session=False
    )
    job_ids = [row[0] for row in db.query(ProcessingJob.id).filter(ProcessingJob.document_id == doc_id).all()]
    if job_ids:
        db.query(JobLog).filter(JobLog.job_id.in_(job_ids)).delete(synchronize_session=False)
    db.query(ProcessingJob).filter(ProcessingJob.document_id == doc_id).delete(synchronize_session=False)
    db.query(Document).filter(Document.duplicate_of == doc_id).update(
        {"duplicate_of": None}, synchronize_session=False
    )
    db.query(CalendarEvent).filter(CalendarEvent.document_id == doc_id).update({"document_id": None})
    db.query(VectorChunk).filter(VectorChunk.document_id == doc_id).delete(synchronize_session=False)
    db.query(LegalHoldItem).filter(LegalHoldItem.document_id == doc_id).delete(synchronize_session=False)
    db.query(CaseDocument).filter(CaseDocument.document_id == doc_id).delete(synchronize_session=False)
    db.query(ReadingConfirmation).filter(ReadingConfirmation.document_id == doc_id).delete(
        synchronize_session=False
    )
    db.query(ArchiveLinkEntry).filter(ArchiveLinkEntry.document_id == doc_id).delete(
        synchronize_session=False
    )
    db.query(CollabOp).filter(CollabOp.document_id == doc_id).delete(synchronize_session=False)
    db.query(FormSubmission).filter(FormSubmission.document_id == doc_id).update(
        {"document_id": None}, synchronize_session=False
    )
    db.query(DocumentLink).filter(
        (DocumentLink.src_id == doc_id) | (DocumentLink.dst_id == doc_id)
    ).delete(synchronize_session=False)
