"""Periodic IMAP mailbox scan tasks."""
from __future__ import annotations

import email
import imaplib
import logging
from datetime import timedelta
from email import policy
from pathlib import Path

from app import database
from app.crypto import decrypt_secret
from app.database import now
from app.extract import matches_glob
from app.hashing import file_sha256
from app.joex import schedule_document
from app.models import AnonymousUpload, Document, Folder, MailboxTask, MailSettings, User
from app.storage import doc_storage_dir, safe_filename, validate_upload_filename

logger = logging.getLogger("newtonedms.mailbox")


def due_tasks(db) -> list[MailboxTask]:
    rows = db.query(MailboxTask).filter(MailboxTask.enabled.is_(True)).all()
    out = []
    for t in rows:
        if t.start_once and t.last_run is not None:
            continue
        mins = t.schedule_minutes or 15
        if t.last_run is None or (now() - t.last_run) >= timedelta(minutes=mins):
            out.append(t)
    return out


def run_task(db, task: MailboxTask) -> int:
    settings_row = db.get(MailSettings, task.mail_settings_id)
    folder = db.get(Folder, task.folder_id)
    owner = db.get(User, task.created_by)
    if not settings_row or not folder or not owner:
        task.last_run = now()
        db.commit()
        return 0
    password = decrypt_secret(settings_row.password_enc)
    host, port = settings_row.host, settings_row.port or 993
    imported = 0
    try:
        if settings_row.use_ssl:
            client = imaplib.IMAP4_SSL(host, port)
        else:
            client = imaplib.IMAP4(host, port)
        client.login(settings_row.username or "", password)
        mailboxes = [m.strip() for m in (task.imap_folders or "INBOX").split(",") if m.strip()]
        since = now() - timedelta(hours=task.received_since_hours or 72)
        since_s = since.strftime("%d-%b-%Y")
        for box in mailboxes:
            typ, _ = client.select(box)
            if typ != "OK":
                continue
            typ, data = client.search(None, "SINCE", since_s)
            if typ != "OK":
                continue
            for uid in (data[0] or b"").split():
                typ, msg_data = client.fetch(uid, "(RFC822)")
                if typ != "OK" or not msg_data or not msg_data[0]:
                    continue
                raw = msg_data[0][1]
                msg = email.message_from_bytes(raw, policy=policy.default)
                subject = str(msg.get("Subject") or "")
                if not matches_glob(subject, task.subject_glob or "*"):
                    continue
                imported += _ingest_message(db, task, folder, owner, msg, raw)
                if task.move_after_import:
                    try:
                        client.copy(uid, task.move_after_import)
                        client.store(uid, "+FLAGS", "\\Deleted")
                    except Exception:
                        logger.warning("move-after-import failed for uid %s", uid)
        client.expunge()
        client.logout()
    except Exception:
        logger.exception("mailbox task %s failed", task.id)
    task.last_run = now()
    db.commit()
    return imported


def _ingest_message(db, task: MailboxTask, folder: Folder, owner: User, msg, raw: bytes) -> int:
    from_ = str(msg.get("From") or "")
    subject = str(msg.get("Subject") or "email")
    source = db.get(AnonymousUpload, task.source_id) if task.source_id else None
    tags = (source.tags if source else "") or ""
    correspondent_id = source.correspondent_id if source else None
    skip_dup = bool(source.skip_duplicates) if source else False
    language = source.language if source else None
    priority = source.priority if source else 0
    direction = None
    if task.direction_from_from and from_:
        mine = (owner.email or "").lower()
        direction = "outgoing" if mine and mine in from_.lower() else "incoming"
    count = 0
    parts = []
    if msg.is_multipart():
        for part in msg.walk():
            if part.get_content_maintype() == "multipart":
                continue
            filename = part.get_filename()
            payload = part.get_payload(decode=True) or b""
            if filename:
                if not matches_glob(filename, task.file_glob or "*"):
                    continue
                parts.append((filename, payload, part.get_content_type()))
            elif part.get_content_type() == "text/plain" and payload:
                parts.append((f"{safe_filename(subject)}.txt", payload, "text/plain"))
    else:
        payload = msg.get_payload(decode=True) or raw
        parts.append((f"{safe_filename(subject)}.eml", payload, "message/rfc822"))
    for name, payload, mime in parts:
        try:
            validate_upload_filename(name)
        except Exception:
            continue
        tmp = database.STORAGE_DIR / f".imap_{safe_filename(name)}"
        tmp.write_bytes(payload)
        digest = file_sha256(tmp)
        if skip_dup and db.query(Document).filter(Document.content_hash == digest).first():
            tmp.unlink(missing_ok=True)
            continue
        d = Document(
            name=safe_filename(name),
            title=subject or name,
            folder_id=folder.id,
            tags=tags,
            created_by=owner.id,
            size=len(payload),
            mime=mime,
            file_path=str(tmp),
            source="imap",
            source_id=source.id if source else None,
            correspondent_id=correspondent_id,
            language=language,
            direction=direction,
            processing_status="pending",
            content_hash=digest,
        )
        db.add(d)
        db.flush()
        dest = doc_storage_dir(d.id) / f"v1{Path(name).suffix or '.bin'}"
        tmp.replace(dest)
        d.file_path = str(dest)
        db.commit()
        schedule_document(db, d.id, created_by=owner.id)
        if priority:
            from app.models import ProcessingJob

            job = (
                db.query(ProcessingJob)
                .filter(ProcessingJob.document_id == d.id)
                .order_by(ProcessingJob.id.desc())
                .first()
            )
            if job:
                job.priority = priority
                db.commit()
        count += 1
    return count


def scan_due() -> int:
    db = database.SessionLocal()
    n = 0
    try:
        for task in due_tasks(db):
            n += run_task(db, task)
    except Exception:
        logger.exception("mailbox scan_due")
    finally:
        db.close()
    return n
