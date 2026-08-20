"""Deliver notifications over Matrix, Gotify, HTTP webhooks, and email."""
from __future__ import annotations

import json
import logging
import smtplib
from email.message import EmailMessage
from typing import Any

from app.config import settings
from app.crypto import decrypt_secret
from app.models import MailSettings, NotifyChannel

logger = logging.getLogger("newtonedms.notify")


def deliver(channel: NotifyChannel, title: str, body: str, payload: dict[str, Any] | None = None) -> bool:
    if not channel or not channel.enabled:
        return False
    kind = (channel.kind or "").lower()
    cfg = dict(channel.config or {})
    try:
        if kind == "gotify":
            return _gotify(cfg, title, body)
        if kind == "matrix":
            return _matrix(cfg, body or title)
        if kind in ("http", "webhook"):
            return _http(cfg, title, body, payload or {})
        if kind == "email":
            return _email(cfg, title, body)
        logger.warning("unknown notify channel kind %s", kind)
        return False
    except Exception:
        logger.exception("notify channel %s failed", channel.id)
        return False


def _gotify(cfg: dict, title: str, body: str) -> bool:
    import httpx

    url = (cfg.get("url") or "").rstrip("/") + "/message"
    token = cfg.get("token") or ""
    r = httpx.post(
        url,
        params={"token": token},
        json={"title": title, "message": body, "priority": int(cfg.get("priority") or 5)},
        timeout=8.0,
    )
    r.raise_for_status()
    return True


def _matrix(cfg: dict, body: str) -> bool:
    import httpx

    homeserver = (cfg.get("homeserver") or "").rstrip("/")
    token = cfg.get("access_token") or cfg.get("token") or ""
    room = cfg.get("room_id") or cfg.get("room") or ""
    if not (homeserver and token and room):
        raise ValueError("matrix channel needs homeserver, access_token, room_id")
    url = f"{homeserver}/_matrix/client/v3/rooms/{room}/send/m.room.message"
    r = httpx.post(
        url,
        params={"access_token": token},
        json={"msgtype": "m.text", "body": body},
        timeout=8.0,
    )
    r.raise_for_status()
    return True


def _http(cfg: dict, title: str, body: str, payload: dict) -> bool:
    import httpx

    url = cfg.get("url") or ""
    if not url.startswith(("http://", "https://")):
        raise ValueError("http channel url must be http(s)")
    r = httpx.post(
        url,
        json={"title": title, "body": body, "payload": payload},
        headers=cfg.get("headers") or {"Content-Type": "application/json"},
        timeout=8.0,
    )
    r.raise_for_status()
    return True


def _email(cfg: dict, title: str, body: str) -> bool:
    host = cfg.get("host")
    port = int(cfg.get("port") or 587)
    username = cfg.get("username") or ""
    password = cfg.get("password") or ""
    to = cfg.get("to") or username
    if not host or not to:
        raise ValueError("email channel needs host and to")
    msg = EmailMessage()
    msg["Subject"] = title
    msg["From"] = username or settings.smtp_from
    msg["To"] = to
    msg.set_content(body)
    use_ssl = bool(cfg.get("use_ssl", port == 465))
    if use_ssl and port == 465:
        with smtplib.SMTP_SSL(host, port, timeout=20) as client:
            if username:
                client.login(username, password)
            client.send_message(msg)
    else:
        with smtplib.SMTP(host, port, timeout=20) as client:
            client.starttls()
            if username:
                client.login(username, password)
            client.send_message(msg)
    return True


def smtp_from_settings(row: MailSettings) -> dict:
    return {
        "host": row.host,
        "port": row.port,
        "username": row.username,
        "password": decrypt_secret(row.password_enc) if row.password_enc else "",
        "use_ssl": row.use_ssl,
        "to": row.username,
    }


def render_digest(title: str, items: list[dict]) -> str:
    lines = [title, ""]
    for it in items:
        lines.append(f"- #{it.get('id')} {it.get('title') or it.get('name')}  due={it.get('due_date') or ''}")
    return "\n".join(lines)
