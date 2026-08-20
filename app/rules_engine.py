"""Event-driven automation rules: conditions → actions on documents."""
from __future__ import annotations

import logging
from typing import Any

from app.miniquery import match
from app.models import AutomationRule, Document, Folder

logger = logging.getLogger("newtonedms.rules")


def fire(db, event: str, doc: Document, extra: dict[str, Any] | None = None) -> list[str]:
    extra = extra or {}
    applied: list[str] = []
    rules = db.query(AutomationRule).filter(AutomationRule.enabled.is_(True), AutomationRule.event == event).all()
    for rule in rules:
        try:
            cond = rule.condition or {}
            if cond and not match(db, doc, cond):
                continue
            for action in rule.actions or []:
                _run_action(db, doc, action, extra)
                applied.append(f"{rule.name}:{action.get('type')}")
        except Exception:
            logger.exception("rule %s failed", rule.id)
    if applied:
        db.commit()
    return applied


def _run_action(db, doc: Document, action: dict, extra: dict) -> None:
    kind = (action.get("type") or action.get("kind") or "").lower()
    if kind == "tag":
        tags = {t.strip() for t in (doc.tags or "").split(",") if t.strip()}
        add = action.get("tags") or action.get("value") or ""
        if isinstance(add, str):
            add = [x.strip() for x in add.split(",") if x.strip()]
        tags |= set(add)
        doc.tags = ",".join(sorted(tags))
    elif kind == "move":
        fid = int(action.get("folder_id") or 0)
        if fid and db.get(Folder, fid):
            doc.folder_id = fid
    elif kind == "status":
        doc.status = str(action.get("status") or action.get("value") or doc.status)
    elif kind == "workflow":
        from app.routers.workflow import start_workflow_internal

        tid = int(action.get("template_id") or 0)
        if tid:
            start_workflow_internal(db, doc.id, tid, created_by=doc.created_by)
    elif kind == "watermark":
        from pathlib import Path
        from app.pdfops import watermark
        from app.storage import doc_storage_dir

        src = Path(doc.pdf_file_path or doc.file_path)
        if src.exists():
            dest = doc_storage_dir(doc.id) / "watermarked.pdf"
            watermark(src, dest, action.get("text") or "CONFIDENTIAL")
            doc.pdf_file_path = str(dest)
    elif kind == "notify":
        from app.models import Notification

        uid = int(action.get("user_id") or doc.created_by)
        db.add(Notification(user_id=uid, message=action.get("message") or f"Rule fired on #{doc.id}"))
    elif kind == "webhook":
        import json
        import urllib.request

        url = action.get("url") or ""
        if url.startswith(("http://", "https://")):
            req = urllib.request.Request(
                url,
                data=json.dumps({"document_id": doc.id, "event": extra.get("event"), "title": doc.title}).encode(),
                headers={"Content-Type": "application/json"},
                method="POST",
            )
            urllib.request.urlopen(req, timeout=5)  # nosec B310
    elif kind == "idp":
        from pathlib import Path
        from app.idp import auto_capture

        auto_capture(db, doc, Path(doc.pdf_file_path or doc.file_path) if doc.file_path else None)
    elif kind == "embed":
        from app.vectors import index_document

        index_document(db, doc.id, doc.title or "", doc.extracted_text or "")
