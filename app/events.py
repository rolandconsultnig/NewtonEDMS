"""Domain events: item created, tag added, confirmed, due — with mini-query filters."""
from __future__ import annotations

import logging
from typing import Any

from app.miniquery import match
from app.models import Document, EventHook, Notification, NotifyChannel
from app.notify_channels import deliver

logger = logging.getLogger("newtonedms.events")


def emit(db, event: str, doc: Document, extra: dict[str, Any] | None = None) -> None:
    extra = extra or {}
    title = f"{event}: {doc.title or doc.name}"
    body = extra.get("message") or f"Item #{doc.id} {doc.title}"
    payload = {"event": event, "document_id": doc.id, "title": doc.title, "tags": doc.tags, **extra}
    hooks = db.query(EventHook).filter(EventHook.enabled.is_(True), EventHook.event == event).all()
    for hook in hooks:
        try:
            if hook.mini_query and not match(db, doc, hook.mini_query):
                continue
            channel = db.get(NotifyChannel, hook.channel_id)
            if channel:
                deliver(channel, title, body, payload)
            else:
                db.add(Notification(user_id=hook.user_id, message=body))
        except Exception:
            logger.exception("event hook %s failed", hook.id)
    db.commit()
