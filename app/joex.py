"""JOEX — NewtonEDMS job executor.

Pipeline for each uploaded document:
  1. Content hash + duplicate detection
  2. Nested archive / EML extraction
  3. Convert to searchable PDF (office, images, HTML, markdown; encrypted PDF)
  4. First-page thumbnail
  5. Text extraction + PDF keyword tags
  6. NLP + learned classifier
  7. Full-text index
  8. Packaged addons + event hooks

Runs in a thread pool; stuck jobs are retried then marked failed. Live logs
are appended to ProcessingJob.log_text and JobLog rows.
"""
from __future__ import annotations

import logging
import shutil
import threading
from concurrent.futures import ThreadPoolExecutor
from datetime import timedelta
from pathlib import Path

from app import database
from app.config import settings
from app.database import now
from app.extract import extract_nested, guess_mime
from app.hashing import file_sha256
from app.indexing import _extract_text, index_document
from app.models import (
    Addon,
    Document,
    DocumentAttachment,
    JobLog,
    Notification,
    ProcessingJob,
    Tag,
)
from app.nlp import analyze
from app.storage import doc_storage_dir

logger = logging.getLogger("newtonedms.joex")

_stop = threading.Event()
_thread: threading.Thread | None = None
_pool: ThreadPoolExecutor | None = None


def _log(db, job_id: int | None, message: str, level: str = "info") -> None:
    logger.log(getattr(logging, level.upper(), logging.INFO), message)
    if not job_id:
        return
    try:
        db.add(JobLog(job_id=job_id, level=level, message=message[:4000]))
        job = db.get(ProcessingJob, job_id)
        if job:
            job.log_text = ((job.log_text or "") + "\n" + message)[-20_000:]
            job.message = message[:500]
        db.commit()
    except Exception:
        db.rollback()


def schedule_document(db, doc_id: int, created_by: int | None = None, priority: int = 0) -> ProcessingJob:
    """Enqueue processing; run inline when ``joex_inline`` is set (tests)."""
    job = enqueue(db, "process_document", document_id=doc_id, created_by=created_by, priority=priority)
    if settings.joex_inline:
        process_document(doc_id, job_id=job.id)
        job = db.get(ProcessingJob, job.id) or job
        if job.status == "queued":
            job.status = "done"
            job.progress = 1.0
            job.finished_at = now()
            db.commit()
    return job


def enqueue(
    db,
    kind: str,
    *,
    document_id: int | None = None,
    created_by: int | None = None,
    priority: int = 0,
    payload: dict | None = None,
) -> ProcessingJob:
    job = ProcessingJob(
        kind=kind,
        document_id=document_id,
        created_by=created_by,
        priority=priority,
        payload=payload or {},
        status="queued",
        max_attempts=settings.joex_max_attempts,
    )
    db.add(job)
    db.commit()
    db.refresh(job)
    return job


def process_document(doc_id: int, job_id: int | None = None) -> None:
    db = database.SessionLocal()
    try:
        d = db.get(Document, doc_id)
        if not d or not d.file_path:
            return
        d.processing_status = "processing"
        db.commit()
        _log(db, job_id, f"processing document {doc_id}")
        from app.backends import resolve

        try:
            path = resolve(d.file_path)
        except FileNotFoundError:
            path = Path(d.file_path)
        dest = doc_storage_dir(d.id)

        if not d.original_file_path:
            original = dest / f"original{path.suffix}"
            if path.exists() and path.resolve() != original.resolve():
                try:
                    shutil.copy2(path, original)
                    d.original_file_path = str(original)
                except OSError:
                    d.original_file_path = str(path)
            else:
                d.original_file_path = str(path)

        if path.exists():
            digest = file_sha256(path)
            d.content_hash = digest
            twin = (
                db.query(Document)
                .filter(Document.content_hash == digest, Document.id != d.id)
                .first()
            )
            if twin:
                d.duplicate_of = twin.id
                meta = dict(d.metadata_json or {})
                meta["duplicate_of"] = twin.id
                d.metadata_json = meta
                _log(db, job_id, f"duplicate of #{twin.id}")

        extracted_extra = ""
        ext = path.suffix.lower()
        if ext in {".zip", ".eml", ".msg"} and path.exists():
            extra, files = extract_nested(path, dest / "extracted")
            extracted_extra += extra
            for f in files:
                db.add(
                    DocumentAttachment(
                        document_id=d.id,
                        name=str(f.relative_to(dest / "extracted")) if (dest / "extracted") in f.parents else f.name,
                        file_path=str(f),
                        size=f.stat().st_size if f.exists() else 0,
                        mime=guess_mime(f),
                        role="extracted",
                    )
                )
                text, _ = _extract_text(f, "")
                extracted_extra += "\n" + text
            _log(db, job_id, f"extracted {len(files)} nested file(s)")

        lang = d.language or "eng"
        password = None
        meta = dict(d.metadata_json or {})
        password = meta.get("pdf_password") or meta.get("password")
        pdf_dest = dest / "converted.pdf"
        try:
            from app.convert import first_page_thumbnail, pdf_keywords, to_pdf

            if path.exists():
                to_pdf(path, pdf_dest, password=password, lang=lang)
                if pdf_dest.exists() and pdf_dest.stat().st_size:
                    d.pdf_file_path = str(pdf_dest)
                    db.add(
                        DocumentAttachment(
                            document_id=d.id,
                            name="converted.pdf",
                            file_path=str(pdf_dest),
                            size=pdf_dest.stat().st_size,
                            mime="application/pdf",
                            role="converted",
                        )
                    )
                    _log(db, job_id, "converted to searchable PDF")
                    for kw in pdf_keywords(pdf_dest if pdf_dest.exists() else path):
                        existing = {t.strip() for t in (d.tags or "").split(",") if t.strip()}
                        if kw.lower() not in {t.lower() for t in existing}:
                            existing.add(kw)
                            if not db.query(Tag).filter(Tag.name == kw).first():
                                db.add(Tag(name=kw, created_by=d.created_by))
                        d.tags = ",".join(sorted(existing))
                thumb = dest / "preview.jpg"
                src_for_thumb = pdf_dest if pdf_dest.exists() else path
                if first_page_thumbnail(src_for_thumb, thumb, dpi=settings.preview_dpi):
                    d.thumbnail_path = str(thumb)
                    _log(db, job_id, "wrote first-page thumbnail")
        except Exception as exc:
            _log(db, job_id, f"conversion skipped: {exc}", "warning")

        text, barcodes = _extract_text(path, d.mime or "")
        if d.pdf_file_path:
            pdf_text, _ = _extract_text(Path(d.pdf_file_path), "application/pdf")
            if pdf_text:
                text = (text or "") + "\n" + pdf_text
        text = (text or "") + extracted_extra
        if barcodes:
            meta = dict(d.metadata_json or {})
            meta["barcodes"] = barcodes
            d.metadata_json = meta
        d.extracted_text = text[:500_000] if text else None
        pdf_for_pages = Path(d.pdf_file_path) if d.pdf_file_path else path
        if pdf_for_pages.suffix.lower() == ".pdf" and pdf_for_pages.exists():
            try:
                import io
                import pdfplumber

                data = pdf_for_pages.read_bytes()
                with pdfplumber.open(io.BytesIO(data)) as pdf:
                    d.page_count = len(pdf.pages)
            except Exception:
                d.page_count = d.page_count or 0

        hints = analyze(db, text or d.title or d.name)
        if hints["language"] and not d.language:
            d.language = hints["language"]
        if hints["item_date"] and not d.item_date:
            d.item_date = hints["item_date"]
        if hints["tags"]:
            existing = {t.strip() for t in (d.tags or "").split(",") if t.strip()}
            merged = existing | set(hints["tags"])
            d.tags = ",".join(sorted(merged))
        if hints["contacts"] and not d.correspondent_id:
            match = hints["contacts"][0]
            if not getattr(match, "concerning_only", False):
                d.correspondent_id = match.id
        if hints.get("organizations") and not d.organization_id:
            d.organization_id = hints["organizations"][0].id
        if hints.get("equipment") and not d.equipment_id:
            eq = hints["equipment"][0]
            d.equipment_id = eq.id
            d.equipment = eq.name
        try:
            from app.classifier import predict

            learned = predict((text or "") + " " + (d.title or ""), top_k=5)
        except Exception:
            learned = []
        meta = dict(d.metadata_json or {})
        meta["suggestions"] = {
            "tags": hints["tags"],
            "dates": hints["dates"],
            "language": hints["language"],
            "contacts": [c.name for c in hints["contacts"]],
            "organizations": [o.name for o in hints.get("organizations") or []],
            "equipment": [e.name for e in hints.get("equipment") or []],
            "classifier": [{"tag": lab, "score": score} for lab, score in learned],
        }
        d.metadata_json = meta
        if learned and not d.confirmed:
            existing = {t.strip().lower() for t in (d.tags or "").split(",") if t.strip()}
            for lab, score in learned:
                if score >= 0.35 and lab not in existing:
                    existing.add(lab)
            d.tags = ",".join(sorted({t for t in (d.tags or "").split(",") if t.strip()} | {lab for lab, s in learned if s >= 0.35}))

        from app.fts import index_text

        index_document(d.id, d.title, d.tags, d.file_path, d.size, content_override=d.extracted_text)
        index_text(d.id, d.title or "", d.tags or "", d.extracted_text or "")

        try:
            from pathlib import Path as _P
            from app.idp import auto_capture

            auto_capture(db, d, _P(d.pdf_file_path) if d.pdf_file_path else path)
        except Exception:
            _log(db, job_id, "idp capture skipped", "warning")
        try:
            from app.vectors import index_document as index_vectors

            index_vectors(db, d.id, d.title or "", d.extracted_text or "")
        except Exception:
            _log(db, job_id, "vector index skipped", "warning")

        d.processing_status = "done"
        d.updated_at = now()
        db.commit()
        _log(db, job_id, "done")

        _fire_addons(db, "on_process", d)
        try:
            from app.addons_run import run_for_event

            run_for_event(db, "on_process", d)
        except Exception:
            logger.exception("packaged addons failed")
        try:
            from app.events import emit

            emit(db, "item_created", d)
            if hints["tags"] or learned:
                emit(db, "tag_added", d, {"tags": d.tags})
        except Exception:
            logger.exception("event emit failed")
        try:
            from app.hooks import after_document_processed

            after_document_processed(db, d)
        except Exception:
            logger.exception("processed hooks failed")
    except Exception:
        logger.exception("process_document failed for %s", doc_id)
        try:
            d = db.get(Document, doc_id)
            if d:
                d.processing_status = "error"
                db.commit()
            _log(db, job_id, "process_document failed", "error")
        except Exception:
            db.rollback()
    finally:
        db.close()


def _fire_addons(db, event: str, doc: Document) -> None:
    import json
    import urllib.request

    addons = (
        db.query(Addon)
        .filter(Addon.enabled.is_(True))
        .filter((Addon.event == event) | (Addon.trigger == event))
        .filter(Addon.webhook_url.isnot(None), Addon.webhook_url != "")
        .all()
    )
    payload = json.dumps(
        {
            "event": event,
            "document_id": doc.id,
            "title": doc.title,
            "tags": doc.tags,
            "processing_status": doc.processing_status,
        }
    ).encode("utf-8")
    for addon in addons:
        try:
            url = addon.webhook_url or ""
            if not url.startswith(("http://", "https://")):
                continue
            req = urllib.request.Request(
                url,
                data=payload,
                headers={"Content-Type": "application/json"},
                method="POST",
            )
            urllib.request.urlopen(req, timeout=5)  # nosec B310 — scheme checked above
        except Exception:
            logger.warning("addon %s webhook failed", addon.name, exc_info=True)


def notify_due_items() -> int:
    db = database.SessionLocal()
    created = 0
    try:
        overdue = (
            db.query(Document)
            .filter(Document.due_date.isnot(None), Document.due_date < now())
            .filter(Document.status != "archived")
            .all()
        )
        for d in overdue:
            exists = (
                db.query(Notification)
                .filter(
                    Notification.user_id == d.created_by,
                    Notification.message.like(f"%overdue document #{d.id}%"),
                )
                .first()
            )
            if exists:
                continue
            db.add(
                Notification(
                    user_id=d.created_by,
                    message=f"Due date passed for overdue document #{d.id}: {d.title}",
                )
            )
            created += 1
            try:
                from app.events import emit

                emit(db, "due", d)
            except Exception:
                pass
        db.commit()
    except Exception:
        logger.exception("notify_due_items failed")
        db.rollback()
    finally:
        db.close()
    return created


def _reclaim_stuck(db) -> int:
    cutoff = now() - timedelta(minutes=settings.joex_stuck_minutes or 30)
    stuck = (
        db.query(ProcessingJob)
        .filter(ProcessingJob.status == "running", ProcessingJob.started_at.isnot(None), ProcessingJob.started_at < cutoff)
        .all()
    )
    n = 0
    for job in stuck:
        job.attempts = (job.attempts or 0) + 1
        max_a = job.max_attempts or settings.joex_max_attempts
        if job.attempts >= max_a:
            job.status = "failed"
            job.finished_at = now()
            job.message = "stuck: moved to failed after retries"
            _log(db, job.id, "stuck → failed", "error")
        else:
            job.status = "queued"
            job.started_at = None
            job.message = "stuck: requeued"
            _log(db, job.id, "stuck → retry", "warning")
        n += 1
    if n:
        db.commit()
    return n


def process_job(job_id: int) -> None:
    db = database.SessionLocal()
    try:
        job = db.get(ProcessingJob, job_id)
        if not job or job.status not in ("queued",):
            return
        job.status = "running"
        job.started_at = now()
        job.attempts = (job.attempts or 0) + 1
        db.commit()
        kind = job.kind
        doc_id = job.document_id
        payload = dict(job.payload or {})
        db.close()
        db = None
        if kind == "process_document" and doc_id:
            process_document(doc_id, job_id=job_id)
        elif kind == "notify_due":
            notify_due_items()
        elif kind == "scan_mailbox":
            from app.mailbox import scan_due

            scan_due()
        elif kind == "train_classifier":
            from app.classifier import train
            from app.models import Collective

            sdb = database.SessionLocal()
            try:
                coll = sdb.get(Collective, payload.get("collective_id")) if payload.get("collective_id") else sdb.query(Collective).first()
                cfg = dict((coll.classifier_config if coll else None) or {})
                train(sdb, whitelist=cfg.get("whitelist") or [], blacklist=cfg.get("blacklist") or [])
            finally:
                sdb.close()
        elif kind == "run_addon":
            from app.addons_run import run_addon

            sdb = database.SessionLocal()
            try:
                addon = sdb.get(Addon, payload.get("addon_id"))
                doc = sdb.get(Document, doc_id or payload.get("document_id"))
                if addon and doc:
                    run_addon(sdb, addon, doc)
            finally:
                sdb.close()
        db = database.SessionLocal()
        job = db.get(ProcessingJob, job_id)
        if job and job.status == "running":
            job.status = "done"
            job.progress = 1.0
            job.finished_at = now()
            db.commit()
    except Exception as exc:
        logger.exception("process_job %s failed", job_id)
        if db is None:
            db = database.SessionLocal()
        job = db.get(ProcessingJob, job_id)
        if job:
            max_a = job.max_attempts or settings.joex_max_attempts
            if (job.attempts or 0) < max_a:
                job.status = "queued"
                job.message = f"retry after error: {exc}"[:500]
            else:
                job.status = "failed"
                job.message = str(exc)[:2000]
                job.finished_at = now()
            db.commit()
    finally:
        if db is not None:
            db.close()


def process_pending_jobs(limit: int | None = None) -> int:
    limit = limit or settings.joex_pool_size or 2
    db = database.SessionLocal()
    try:
        _reclaim_stuck(db)
        jobs = (
            db.query(ProcessingJob)
            .filter(ProcessingJob.status == "queued")
            .order_by(ProcessingJob.priority.desc(), ProcessingJob.id.asc())
            .limit(limit)
            .all()
        )
        ids = [j.id for j in jobs]
    finally:
        db.close()
    for jid in ids:
        process_job(jid)
    return len(ids)


def _worker_loop() -> None:
    logger.info("JOEX worker started (pool=%s)", settings.joex_pool_size)
    global _pool
    _pool = ThreadPoolExecutor(max_workers=max(1, settings.joex_pool_size), thread_name_prefix="joex")
    while not _stop.is_set():
        try:
            try:
                from app.cluster import heartbeat

                heartbeat("joex")
            except Exception:
                pass
            db = database.SessionLocal()
            try:
                _reclaim_stuck(db)
                jobs = (
                    db.query(ProcessingJob)
                    .filter(ProcessingJob.status == "queued")
                    .order_by(ProcessingJob.priority.desc(), ProcessingJob.id.asc())
                    .limit(settings.joex_pool_size)
                    .all()
                )
                ids = [j.id for j in jobs]
            finally:
                db.close()
            if not ids:
                _stop.wait(settings.joex_poll_seconds)
                continue
            futs = [_pool.submit(process_job, jid) for jid in ids]
            for f in futs:
                try:
                    f.result()
                except Exception:
                    logger.exception("pool job failed")
        except Exception:
            logger.exception("JOEX worker loop error")
            _stop.wait(5)
    logger.info("JOEX worker stopped")


def start_worker() -> None:
    global _thread
    if _thread and _thread.is_alive():
        return
    _stop.clear()
    _thread = threading.Thread(target=_worker_loop, name="newton-joex", daemon=True)
    _thread.start()


def stop_worker() -> None:
    _stop.set()
    if _pool:
        _pool.shutdown(wait=False)
    if _thread:
        _thread.join(timeout=5)
