"""SMTP gateway and HTTP push-ingest for immediate mail/file arrival."""
from __future__ import annotations

import email
import logging
import threading
from email import policy
from pathlib import Path

from app import database
from app.config import settings
from app.hashing import file_sha256
from app.joex import schedule_document
from app.models import AnonymousUpload, Document, Folder, User
from app.storage import doc_storage_dir, safe_filename, validate_upload_filename

logger = logging.getLogger("newtonedms.smtp_gateway")

_thread: threading.Thread | None = None
_controller = None


def ingest_rfc822(raw: bytes, *, token: str | None = None, folder_id: int | None = None, user_id: int | None = None) -> list[int]:
    """Parse a raw RFC822 message and create document items. Returns new ids."""
    db = database.SessionLocal()
    created: list[int] = []
    try:
        source = None
        if token:
            source = db.query(AnonymousUpload).filter(AnonymousUpload.token == token, AnonymousUpload.enabled.is_(True)).first()
        folder = None
        owner = None
        if source:
            folder = db.get(Folder, source.folder_id)
            owner = db.get(User, source.created_by)
        elif folder_id and user_id:
            folder = db.get(Folder, folder_id)
            owner = db.get(User, user_id)
        if not folder or not owner:
            raise ValueError("ingest target folder/owner missing")
        msg = email.message_from_bytes(raw, policy=policy.default)
        subject = str(msg.get("Subject") or "inbound")
        parts: list[tuple[str, bytes, str]] = []
        if msg.is_multipart():
            for part in msg.walk():
                if part.get_content_maintype() == "multipart":
                    continue
                filename = part.get_filename()
                payload = part.get_payload(decode=True) or b""
                if not payload:
                    continue
                name = safe_filename(filename or f"{subject}.txt")
                parts.append((name, payload, part.get_content_type() or "application/octet-stream"))
        else:
            payload = msg.get_payload(decode=True) or raw
            parts.append((f"{safe_filename(subject)}.eml", payload, "message/rfc822"))
        skip = bool(source.skip_duplicates) if source else False
        for name, payload, mime in parts:
            try:
                validate_upload_filename(name)
            except Exception:
                continue
            tmp = database.STORAGE_DIR / f".push_{safe_filename(name)}"
            tmp.write_bytes(payload)
            digest = file_sha256(tmp)
            if skip and db.query(Document).filter(Document.content_hash == digest).first():
                tmp.unlink(missing_ok=True)
                continue
            d = Document(
                name=name,
                title=subject or name,
                folder_id=folder.id,
                tags=(source.tags if source else "") or "",
                created_by=owner.id,
                size=len(payload),
                mime=mime,
                file_path=str(tmp),
                source="smtp" if token is None else "push",
                source_id=source.id if source else None,
                correspondent_id=source.correspondent_id if source else None,
                language=source.language if source else None,
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
            created.append(d.id)
        return created
    finally:
        db.close()


class _Handler:
    async def handle_DATA(self, server, session, envelope):  # noqa: N802
        try:
            ingest_rfc822(envelope.content, token=_token_from_rcpt(envelope.rcpt_tos))
        except Exception:
            logger.exception("smtp gateway ingest failed")
            return "451 ingest failed"
        return "250 OK"


def _token_from_rcpt(rcpts: list[str]) -> str | None:
    for r in rcpts or []:
        local = (r or "").split("@", 1)[0]
        if local.startswith("ingest+"):
            return local.split("ingest+", 1)[1]
        if local.startswith("u+"):
            return local.split("u+", 1)[1]
    return None


def start_gateway() -> None:
    global _thread, _controller
    if not settings.smtp_gateway_enabled:
        return
    if _thread and _thread.is_alive():
        return

    def _run():
        global _controller
        try:
            from aiosmtpd.controller import Controller

            _controller = Controller(
                _Handler(),
                hostname=settings.smtp_gateway_host,
                port=settings.smtp_gateway_port,
            )
            _controller.start()
            logger.info("SMTP gateway listening on %s:%s", settings.smtp_gateway_host, settings.smtp_gateway_port)
        except Exception:
            logger.exception("SMTP gateway failed to start")

    _thread = threading.Thread(target=_run, name="newton-smtp", daemon=True)
    _thread.start()


def stop_gateway() -> None:
    global _controller
    if _controller is not None:
        try:
            _controller.stop()
        except Exception:
            pass
        _controller = None
