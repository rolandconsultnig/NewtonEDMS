"""Background scheduled tasks (index, import, retention, notifications)."""
from __future__ import annotations

import logging
import threading
from datetime import timedelta

from app import database
from app.database import now
from app.models import Document, Folder, ScheduledTask

logger = logging.getLogger("newtonedms.scheduler")
_stop = threading.Event()
_thread: threading.Thread | None = None

DEFAULTS = (
    ("Stats collector", "stats", 60),
    ("Digest processor", "digest", 30),
    ("Path calculator", "paths", 120),
    ("Index maintenance", "index", 180),
    ("Import folder scan", "import", 15),
    ("Retention apply", "retention", 1440),
    ("Due notifications", "notify", 60),
    ("Mailbox scan", "mailbox", 15),
    ("Classifier retrain", "classifier", 1440),
    ("Cluster heartbeat", "cluster", 1),
    ("IDP model train", "idp", 1440),
    ("Vector reindex", "vectors", 360),
)


def ensure_default_tasks(db) -> None:
    existing = {t.kind for t in db.query(ScheduledTask).all()}
    for name, kind, mins in DEFAULTS:
        if kind not in existing:
            db.add(ScheduledTask(name=name, kind=kind, interval_minutes=mins, enabled=True))
    db.commit()


def run_task(db, task: ScheduledTask) -> None:
    task.last_run = now()
    try:
        if task.kind == "stats":
            n = db.query(Document).filter(Document.deleted_at.is_(None)).count()
            task.last_message = f"{n} live documents"
        elif task.kind == "digest":
            from app.models import Notification, NotificationRule
            from app.notify_channels import deliver, render_digest
            from app.querylang import apply_filters, parse_query

            sent = 0
            for rule in db.query(NotificationRule).filter(NotificationRule.enabled.is_(True), NotificationRule.digest.is_(True)).all():
                parsed = parse_query(rule.query or "due:overdue")
                q = apply_filters(db.query(Document).filter(Document.deleted_at.is_(None)), parsed, db)
                hits = q.limit(50).all()
                inc = {t.strip().lower() for t in (rule.include_tags or "").split(",") if t.strip()}
                exc = {t.strip().lower() for t in (rule.exclude_tags or "").split(",") if t.strip()}
                filtered = []
                for d in hits:
                    tags = {t.strip().lower() for t in (d.tags or "").split(",") if t.strip()}
                    if inc and not (tags & inc):
                        continue
                    if exc and (tags & exc):
                        continue
                    filtered.append(d)
                if not filtered:
                    rule.last_run = now()
                    continue
                body = render_digest(rule.name, [{"id": d.id, "title": d.title, "name": d.name, "due_date": str(d.due_date or "")} for d in filtered])
                db.add(Notification(user_id=rule.user_id, message=body[:500]))
                if rule.channel_id:
                    from app.models import NotifyChannel

                    ch = db.get(NotifyChannel, rule.channel_id)
                    if ch:
                        deliver(ch, rule.name, body, {"event": "due_digest", "count": len(filtered)})
                sent += 1
                rule.last_run = now()
            db.commit()
            task.last_message = f"digest {sent}"
        elif task.kind == "mailbox":
            from app.mailbox import scan_due

            n = scan_due()
            task.last_message = f"imported {n}"
        elif task.kind == "classifier":
            from app.classifier import train
            from app.models import Collective

            coll = db.query(Collective).first()
            cfg = dict((coll.classifier_config if coll else None) or {})
            stats = train(db, whitelist=cfg.get("whitelist") or [], blacklist=cfg.get("blacklist") or [])
            task.last_message = json.dumps(stats) if False else f"trained {stats}"
        elif task.kind == "paths":
            folders = db.query(Folder).filter(Folder.deleted_at.is_(None)).count()
            task.last_message = f"{folders} folders"
        elif task.kind == "index":
            from app.indexing import index_document

            n = 0
            for d in db.query(Document).filter(Document.deleted_at.is_(None), Document.indexable != "unindexable").limit(50).all():
                if d.file_path:
                    index_document(d.id, d.title, d.tags, d.file_path, d.size or 0)
                    n += 1
            task.last_message = f"reindexed {n}"
        elif task.kind == "import":
            from app.models import ImportFolder, User
            from app.routers.ingestion import execute_import_scan

            admin = db.query(User).filter(User.role.in_(("superadmin", "admin"))).first()
            n = 0
            if admin:
                for row in db.query(ImportFolder).filter(ImportFolder.active.is_(True)).all():
                    try:
                        execute_import_scan(db, admin, row)
                        n += 1
                    except Exception as e:
                        logger.warning("import scan %s: %s", row.id, e)
            task.last_message = f"scanned {n} import folders"
        elif task.kind == "retention":
            from app.retention import apply_all

            stats = apply_all(db)
            task.last_message = f"affected {stats['affected']} skipped_holds {stats['skipped_holds']}"
        elif task.kind == "cluster":
            from app.cluster import heartbeat

            info = heartbeat("api")
            task.last_message = f"node {info['node_id']} leader={info['leader']}"
        elif task.kind == "idp":
            from app.idp import train

            stats = train(db)
            task.last_message = f"idp {stats}"
        elif task.kind == "vectors":
            from app.vectors import index_document as index_vectors

            n = 0
            for d in db.query(Document).filter(Document.deleted_at.is_(None), Document.extracted_text.isnot(None)).limit(80).all():
                index_vectors(db, d.id, d.title or "", d.extracted_text or "")
                n += 1
            task.last_message = f"embedded {n}"
        elif task.kind == "notify":
            from app.models import Notification, NotificationRule
            from app.querylang import apply_filters, parse_query
            from app.miniquery import match as mini_match

            sent = 0
            for rule in db.query(NotificationRule).filter(NotificationRule.enabled.is_(True)).all():
                parsed = parse_query(rule.query)
                q = apply_filters(db.query(Document).filter(Document.deleted_at.is_(None)), parsed, db)
                hits = q.limit(20).all()
                if rule.mini_query:
                    hits = [d for d in hits if mini_match(db, d, rule.mini_query)]
                if hits:
                    db.add(Notification(user_id=rule.user_id, message=f"{rule.name}: {len(hits)} match(es)"))
                    if rule.channel_id:
                        from app.models import NotifyChannel
                        from app.notify_channels import deliver

                        ch = db.get(NotifyChannel, rule.channel_id)
                        if ch:
                            deliver(ch, rule.name, f"{len(hits)} match(es)", {"event": rule.event or "query"})
                    sent += 1
                rule.last_run = now()
            db.commit()
            task.last_message = f"notified {sent}"
        else:
            task.last_message = "unknown kind"
        task.last_status = "ok"
    except Exception as e:
        logger.exception("scheduled task %s", task.kind)
        task.last_status = "error"
        task.last_message = str(e)
    db.commit()


def _loop():
    while not _stop.wait(30):
        db = database.SessionLocal()
        try:
            from app.cluster import heartbeat

            info = heartbeat("api")
            leader = bool(info.get("is_leader"))
            ensure_default_tasks(db)
            for t in db.query(ScheduledTask).filter(ScheduledTask.enabled.is_(True)).all():
                if t.kind != "cluster" and not leader:
                    continue
                due = t.last_run is None or (now() - t.last_run) >= timedelta(minutes=t.interval_minutes or 60)
                if due:
                    run_task(db, t)
        except Exception:
            logger.exception("scheduler loop")
        finally:
            db.close()


def start_scheduler():
    global _thread
    if _thread and _thread.is_alive():
        return
    _stop.clear()
    _thread = threading.Thread(target=_loop, name="newton-scheduler", daemon=True)
    _thread.start()


def stop_scheduler():
    _stop.set()
