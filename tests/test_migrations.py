"""Verify the Alembic migrations build the full schema from scratch."""
from __future__ import annotations

import sqlite3
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]


def test_upgrade_head_creates_full_schema(tmp_path):
    from alembic import command
    from alembic.config import Config

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
    }
    assert expected.issubset(tables)


def test_migration_enforces_document_file_path_not_null(tmp_path):
    """Regression: the schema must mark documents.file_path NOT NULL."""
    from alembic import command
    from alembic.config import Config

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
