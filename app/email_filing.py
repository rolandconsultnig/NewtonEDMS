"""Deep email integration: parse .eml / RFC 822 / .msg, extract attachments and file into matters."""
from __future__ import annotations

import email
from email import policy
from email.parser import BytesParser
import io
import logging
from pathlib import Path
from typing import Any

from fastapi import HTTPException
from sqlalchemy.orm import Session

from app.config import BASE_DIR
from app.database import now
from app.legal_matter_engine import attach_document_to_matter
from app.models import Document, Matter, User

logger = logging.getLogger("newtonedms.legal.email")


def parse_and_file_email(
    db: Session,
    user: User,
    matter_id: int,
    raw_bytes: bytes,
    filename: str = "message.eml",
    folder_id: int = 1,
) -> dict[str, Any]:
    """Parse raw RFC 822 email bytes, create documents for email and attachments, and link to matter."""
    matter = db.get(Matter, matter_id)
    if not matter:
        raise HTTPException(status_code=404, detail="Matter not found.")

    storage_root = BASE_DIR / "storage"
    storage_root.mkdir(parents=True, exist_ok=True)

    try:
        msg = BytesParser(policy=policy.default).parsebytes(raw_bytes)
    except Exception as e:
        logger.error("Failed to parse email message: %s", e)
        raise HTTPException(status_code=400, detail=f"Invalid email format: {e}")

    subject = str(msg.get("subject", "No Subject")).strip()
    from_addr = str(msg.get("from", "")).strip()
    to_addr = str(msg.get("to", "")).strip()
    cc_addr = str(msg.get("cc", "")).strip()
    date_str = str(msg.get("date", "")).strip()
    msg_id = str(msg.get("message-id", "")).strip()

    # Extract text and HTML body
    body_text = ""
    body_html = ""
    attachments: list[dict[str, Any]] = []

    if msg.is_multipart():
        for part in msg.walk():
            content_disposition = str(part.get("content-disposition", "")).lower()
            content_type = part.get_content_type()
            filename_part = part.get_filename()

            if "attachment" in content_disposition or filename_part:
                payload = part.get_payload(decode=True)
                if payload:
                    attachments.append({
                        "filename": filename_part or "attachment.dat",
                        "content_type": content_type,
                        "data": payload,
                        "size": len(payload),
                    })
            elif content_type == "text/plain" and not body_text:
                payload = part.get_payload(decode=True)
                if payload:
                    body_text = payload.decode(errors="replace")
            elif content_type == "text/html" and not body_html:
                payload = part.get_payload(decode=True)
                if payload:
                    body_html = payload.decode(errors="replace")
    else:
        payload = msg.get_payload(decode=True)
        if payload:
            body_text = payload.decode(errors="replace")

    # 1. Save the main email document
    email_doc_name = f"Email - {subject[:80]} - {filename}"
    rel_path = f"emails/{now().strftime('%Y%m%d_%H%M%S')}_{filename}"
    target_file = storage_root / rel_path
    target_file.parent.mkdir(parents=True, exist_ok=True)
    target_file.write_bytes(raw_bytes)

    email_meta = {
        "email_subject": subject,
        "email_from": from_addr,
        "email_to": to_addr,
        "email_cc": cc_addr,
        "email_date": date_str,
        "email_message_id": msg_id,
        "attachment_count": len(attachments),
    }

    email_doc = Document(
        name=email_doc_name,
        title=f"Email: {subject}",
        file_path=str(rel_path).replace("\\", "/"),
        mime="message/rfc822",
        size=len(raw_bytes),
        folder_id=folder_id,
        created_by=user.id,
        created_at=now(),
        extracted_text=f"Subject: {subject}\nFrom: {from_addr}\nTo: {to_addr}\nDate: {date_str}\n\n{body_text}",
        metadata_json=email_meta,
        tags=f"email,correspondence,matter-{matter.matter_number}",
        status="active",
    )
    db.add(email_doc)
    db.commit()
    db.refresh(email_doc)

    # Link email document to matter
    attach_document_to_matter(
        db, user, matter_id, email_doc.id,
        category="correspondence",
        confidentiality="confidential",
        notes=f"Email from {from_addr} to {to_addr} sent on {date_str}",
    )

    # 2. Save and link attachments
    created_attachments = []
    for att in attachments:
        att_name = att["filename"]
        att_rel = f"emails/attachments/{now().strftime('%Y%m%d_%H%M%S')}_{att_name}"
        att_file = storage_root / att_rel
        att_file.parent.mkdir(parents=True, exist_ok=True)
        att_file.write_bytes(att["data"])

        att_doc = Document(
            name=f"Attachment: {att_name} (from: {subject[:40]})",
            title=att_name,
            file_path=str(att_rel).replace("\\", "/"),
            mime=att["content_type"],
            size=att["size"],
            folder_id=folder_id,
            created_by=user.id,
            created_at=now(),
            metadata_json={"parent_email_id": email_doc.id, "email_subject": subject},
            tags=f"attachment,discovery,matter-{matter.matter_number}",
            status="active",
        )
        db.add(att_doc)
        db.commit()
        db.refresh(att_doc)

        attach_document_to_matter(
            db, user, matter_id, att_doc.id,
            category="discovery",
            confidentiality="confidential",
            notes=f"Attached to email '{subject}'",
        )
        created_attachments.append({"id": att_doc.id, "title": att_doc.title, "size": att_doc.size})

    return {
        "status": "success",
        "email_document_id": email_doc.id,
        "subject": subject,
        "from": from_addr,
        "to": to_addr,
        "attachment_count": len(attachments),
        "attachments": created_attachments,
        "matter_id": matter_id,
        "matter_number": matter.matter_number,
    }
