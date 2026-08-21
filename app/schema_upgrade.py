"""Bring an existing database up to the current ORM schema.

``create_all`` only creates *missing tables*; it will not add columns to an
already-created table. This helper ALTER TABLEs the gaps so ``py main.py``
recovers without a manual alembic stamp.
"""
from __future__ import annotations

import logging

from sqlalchemy import inspect, text

logger = logging.getLogger("newtonedms.schema")

_NEW_COLUMNS: dict[str, dict[str, str]] = {
    "collectives": {
        "language": "VARCHAR DEFAULT 'eng'",
        "classifier_config": "JSON",
        "invite_code": "VARCHAR",
        "settings": "JSON",
    },
    "users": {
        "collective_id": "INTEGER",
        "totp_secret": "VARCHAR",
        "totp_enabled": "BOOLEAN DEFAULT 0",
        "theme": "VARCHAR DEFAULT 'light'",
        "avatar": "VARCHAR",
        "locale": "VARCHAR DEFAULT 'en'",
        "density": "VARCHAR DEFAULT 'standard'",
        "quota_bytes": "INTEGER DEFAULT 0",
        "last_login_at": "DATETIME",
        "working_hours": "JSON",
        "ldap_dn": "VARCHAR",
        "ui_settings": "JSON",
        "oidc_sub": "VARCHAR",
        "password_changed_at": "DATETIME",
        "failed_logins": "INTEGER DEFAULT 0",
        "locked_until": "DATETIME",
    },
    "folders": {
        "kind": "VARCHAR DEFAULT 'folder'",
        "color": "VARCHAR",
        "quota_bytes": "INTEGER DEFAULT 0",
        "max_children": "INTEGER DEFAULT 0",
        "deleted_at": "DATETIME",
        "deleted_by": "INTEGER",
        "alias_of_id": "INTEGER",
        "template_id": "INTEGER",
        "interface_opts": "JSON",
        "collective_id": "INTEGER",
    },
    "contacts": {
        "concerning_only": "BOOLEAN DEFAULT 0",
        "websites": "JSON",
        "emails": "JSON",
        "channels": "JSON",
        "organization_id": "INTEGER",
        "collective_id": "INTEGER",
    },
    "tags": {
        "collective_id": "INTEGER",
    },
    "custom_fields": {
        "collective_id": "INTEGER",
    },
    "documents": {
        "content_hash": "VARCHAR",
        "correspondent_id": "INTEGER",
        "concerning_id": "INTEGER",
        "due_date": "DATETIME",
        "item_date": "DATETIME",
        "source": "VARCHAR DEFAULT 'upload'",
        "language": "VARCHAR",
        "notes": "TEXT",
        "original_file_path": "VARCHAR",
        "pdf_file_path": "VARCHAR",
        "processing_status": "VARCHAR DEFAULT 'pending'",
        "direction": "VARCHAR",
        "equipment": "VARCHAR",
        "custom_id": "VARCHAR",
        "extracted_text": "TEXT",
        "duplicate_of": "INTEGER",
        "deleted_at": "DATETIME",
        "deleted_by": "INTEGER",
        "locked_by": "INTEGER",
        "immutable": "BOOLEAN DEFAULT 0",
        "file_password_hash": "VARCHAR",
        "indexable": "VARCHAR DEFAULT 'indexable'",
        "rating": "INTEGER DEFAULT 0",
        "color": "VARCHAR",
        "page_count": "INTEGER DEFAULT 0",
        "alias_of_id": "INTEGER",
        "signed": "BOOLEAN DEFAULT 0",
        "confirmed": "BOOLEAN DEFAULT 0",
        "confirmed_at": "DATETIME",
        "organization_id": "INTEGER",
        "equipment_id": "INTEGER",
        "source_id": "INTEGER",
        "thumbnail_path": "VARCHAR",
        "legal_hold": "BOOLEAN DEFAULT 0",
        "case_id": "INTEGER",
        "matter_id": "INTEGER",
        "collab_rev": "INTEGER DEFAULT 0",
        "collective_id": "INTEGER",
    },
    "share_links": {
        "password_hash": "VARCHAR",
        "name": "VARCHAR",
        "kind": "VARCHAR DEFAULT 'download'",
    },
    "permissions": {
        "bits": "INTEGER DEFAULT 0",
    },
    "bookmarks": {
        "kind": "VARCHAR DEFAULT 'query'",
        "resource_id": "INTEGER",
    },
    "workflow_templates": {
        "graph": "JSON",
        "routing_type": "VARCHAR DEFAULT 'sequential'",
        "form_schema": "JSON",
        "sla_hours": "INTEGER DEFAULT 24",
        "escalate_to_role": "VARCHAR DEFAULT 'manager'",
        "auto_approval_rule": "VARCHAR",
    },
    "workflow_instances": {
        "current_node": "VARCHAR",
        "tokens": "JSON",
        "context": "JSON",
        "variables": "JSON",
    },
    "tasks": {
        "node_id": "VARCHAR",
        "routing_type": "VARCHAR DEFAULT 'sequential'",
        "assignee_role": "VARCHAR",
        "action_taken": "VARCHAR",
        "form_data": "JSON",
        "form_schema": "JSON",
        "signature": "VARCHAR",
        "sla_hours": "INTEGER",
        "escalated": "BOOLEAN DEFAULT 0",
        "escalated_to_id": "INTEGER",
        "escalated_at": "DATETIME",
    },
    "import_folders": {
        "protocol": "VARCHAR DEFAULT 'local'",
        "host": "VARCHAR",
        "port": "INTEGER",
        "username": "VARCHAR",
        "password_enc": "VARCHAR",
        "remote_path": "VARCHAR",
    },
    "processing_jobs": {
        "attempts": "INTEGER DEFAULT 0",
        "max_attempts": "INTEGER DEFAULT 3",
        "log_text": "TEXT",
    },
    "dashboards": {
        "collective_id": "INTEGER",
        "scope": "VARCHAR DEFAULT 'personal'",
    },
    "anonymous_uploads": {
        "skip_duplicates": "BOOLEAN DEFAULT 0",
        "priority": "INTEGER DEFAULT 0",
        "language": "VARCHAR",
    },
    "notification_rules": {
        "include_tags": "VARCHAR DEFAULT ''",
        "exclude_tags": "VARCHAR DEFAULT ''",
        "channel_id": "INTEGER",
        "event": "VARCHAR DEFAULT 'query'",
        "mini_query": "JSON",
        "digest": "BOOLEAN DEFAULT 0",
    },
    "addons": {
        "package_path": "VARCHAR",
        "descriptor": "JSON",
        "trigger": "VARCHAR DEFAULT 'on_process'",
        "sandbox": "VARCHAR DEFAULT 'subprocess'",
    },
    "stores": {
        "config": "JSON",
    },
    "comments": {
        "author_name": "VARCHAR",
    },
}


def ensure_columns(engine) -> list[str]:
    """Add any missing columns. Returns the ALTER statements applied."""
    insp = inspect(engine)
    tables = set(insp.get_table_names())
    applied: list[str] = []
    with engine.begin() as conn:
        for table, cols in _NEW_COLUMNS.items():
            if table not in tables:
                continue
            have = {c["name"] for c in inspect(conn).get_columns(table)}
            for name, ddl in cols.items():
                if name in have:
                    continue
                stmt = f"ALTER TABLE {table} ADD COLUMN {name} {ddl}"
                conn.execute(text(stmt))
                applied.append(stmt)
                logger.info("schema upgrade: %s", stmt)
    return applied
