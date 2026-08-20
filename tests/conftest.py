"""Shared pytest fixtures.

Each test gets an isolated FastAPI ``TestClient`` backed by an in-memory SQLite
database and a temporary storage directory, so the real ``edms.db`` and
``storage/`` are never touched.

Set ``EDMS_TEST_DATABASE_URL`` (e.g. a throwaway Postgres database) to run the
whole suite against an external engine instead — useful to validate a
PostgreSQL deployment target. The schema is dropped and recreated per test.
"""
from __future__ import annotations

import os
import sys
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

# Make the project root importable so `import app` works from within tests/.
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app import database as db_mod  # noqa: E402
from app import models  # noqa: E402
from app.config import settings  # noqa: E402
from app.limiter import limiter  # noqa: E402
from app.main import app  # noqa: E402

EXTERNAL_TEST_DB = os.environ.get("EDMS_TEST_DATABASE_URL", "")


def _login(client: TestClient, username: str = "admin", password: str = "admin123") -> str:
    resp = client.post("/api/auth/login", data={"username": username, "password": password})
    assert resp.status_code == 200, resp.text
    return resp.json()["access_token"]


@pytest.fixture()
def client(tmp_path, monkeypatch):
    # Fresh database per test, built via the app's engine factory so SQLite FK
    # enforcement is active. EDMS_TEST_DATABASE_URL switches the whole suite to
    # an external engine (e.g. Postgres) to validate a deployment target.
    if EXTERNAL_TEST_DB:
        engine = db_mod.create_db_engine(EXTERNAL_TEST_DB)
        db_mod.Base.metadata.drop_all(bind=engine)
    else:
        engine = db_mod.create_db_engine("sqlite:///:memory:", poolclass=StaticPool)
    db_mod.engine = engine
    db_mod.SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
    db_mod.Base.metadata.create_all(bind=engine)

    # Isolate file storage and keep the login limiter generous for most tests.
    storage = tmp_path / "storage"
    storage.mkdir()
    monkeypatch.setattr(db_mod, "STORAGE_DIR", storage)
    monkeypatch.setattr(settings, "login_rate_limit", "1000/minute")
    monkeypatch.setattr(settings, "joex_inline", True)
    monkeypatch.setattr(settings, "joex_enabled", False)
    limiter.reset()

    with TestClient(app) as c:
        yield c

    db_mod.Base.metadata.drop_all(bind=engine)


@pytest.fixture()
def admin_token(client) -> str:
    return _login(client)


@pytest.fixture()
def root_folder_id(client) -> int:
    # ``GET /api/folders`` lists the root's *children* (empty on a fresh DB),
    # so resolve the seeded root folder id straight from the test database.
    db = db_mod.SessionLocal()
    try:
        root = db.query(models.Folder).filter(models.Folder.parent_id.is_(None)).first()
        assert root is not None, "root folder was not seeded"
        return root.id
    finally:
        db.close()


def _auth(token: str) -> dict:
    return {"Authorization": f"Bearer {token}"}
