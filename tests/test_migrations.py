"""Verify the Alembic migrations build the full schema from scratch."""
from __future__ import annotations

import sqlite3
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]


def test_upgrade_head_creates_full_schema(tmp_path):
    from alembic.config import Config

    from alembic import command

    db_path = tmp_path / "mig.db"
    cfg = Config(str(PROJECT_ROOT / "alembic.ini"))
    cfg.set_main_option("sqlalchemy.url", f"sqlite:///{db_path.as_posix()}")

    command.upgrade(cfg, "head")

    con = sqlite3.connect(db_path)
    try:
        tables = {
            row[0]
            for row in con.execute("SELECT name FROM sqlite_master WHERE type='table'")
        }
    finally:
        con.close()

    expected = {
        "users", "groups", "user_groups", "folders", "documents",
        "document_versions", "permissions", "audit_logs", "revoked_tokens",
        "comments", "share_links", "retention_policies", "workflow_templates",
        "workflow_instances", "tasks", "notifications", "calendar_events",
        "metadata_templates", "import_folders",
        "collectives", "contacts", "tags", "document_attachments",
        "custom_fields", "custom_field_values", "processing_jobs",
        "bookmarks", "dashboards", "anonymous_uploads", "mail_settings",
        "notification_rules", "addons",
    }
    assert expected.issubset(tables)


def test_migration_enforces_document_file_path_not_null(tmp_path):
    """Regression: the schema must mark documents.file_path NOT NULL."""
    from alembic.config import Config

    from alembic import command

    db_path = tmp_path / "mig.db"
    cfg = Config(str(PROJECT_ROOT / "alembic.ini"))
    cfg.set_main_option("sqlalchemy.url", f"sqlite:///{db_path.as_posix()}")
    command.upgrade(cfg, "head")

    con = sqlite3.connect(db_path)
    try:
        row = con.execute("PRAGMA table_info(documents)").fetchall()
    finally:
        con.close()

    file_path_col = {r[1]: r[3] for r in row}  # name -> notnull flag
    assert file_path_col["file_path"] == 1  # 1 == NOT NULL


def test_ensure_columns_upgrades_legacy_users_table(tmp_path):
    """Existing DBs created before NewtonEDMS must gain totp_enabled without alembic."""
    from sqlalchemy import create_engine, text

    from app.schema_upgrade import ensure_columns

    db_path = tmp_path / "legacy.db"
    engine = create_engine(f"sqlite:///{db_path.as_posix()}")
    with engine.begin() as conn:
        conn.execute(
            text(
                "CREATE TABLE users (id INTEGER PRIMARY KEY, username VARCHAR, "
                "email VARCHAR, hashed_password VARCHAR, role VARCHAR, "
                "is_active BOOLEAN, created_at DATETIME)"
            )
        )
        conn.execute(
            text(
                "CREATE TABLE documents (id INTEGER PRIMARY KEY, name VARCHAR, "
                "title VARCHAR, folder_id INTEGER, current_version INTEGER, "
                "status VARCHAR, checked_out_by INTEGER, size INTEGER, mime VARCHAR, "
                "file_path VARCHAR, tags VARCHAR, metadata JSON, created_by INTEGER, "
                "created_at DATETIME, updated_at DATETIME)"
            )
        )
        conn.execute(
            text(
                "CREATE TABLE share_links (id INTEGER PRIMARY KEY, token VARCHAR, "
                "document_id INTEGER, created_by INTEGER, expires_at DATETIME, "
                "max_downloads INTEGER, download_count INTEGER, created_at DATETIME)"
            )
        )
    applied = ensure_columns(engine)
    assert any("totp_enabled" in s for s in applied)
    with engine.connect() as conn:
        user_cols = {r[1] for r in conn.execute(text("PRAGMA table_info(users)"))}
        doc_cols = {r[1] for r in conn.execute(text("PRAGMA table_info(documents)"))}
        share_cols = {r[1] for r in conn.execute(text("PRAGMA table_info(share_links)"))}
    assert "totp_enabled" in user_cols
    assert "theme" in user_cols
    assert "content_hash" in doc_cols
    assert "processing_status" in doc_cols
    assert "password_hash" in share_cols
    # Idempotent.
    assert ensure_columns(engine) == []
