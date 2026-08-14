"""Regression tests for the feature-module security fixes (audit round)."""
import io
import zipfile
from datetime import timedelta

from app import database as db_mod
from app import models
from app.config import settings
from app.database import now


def _auth(token):
    return {"Authorization": f"Bearer {token}"}


def _register(client, username, password="pw123456"):
    tok = client.post(
        "/api/auth/register", data={"username": username, "password": password}
    ).json()["access_token"]
    return _auth(tok)


def _upload(client, headers, folder_id, title, payload=b"x"):
    return client.post(
        "/api/documents",
        headers=headers,
        data={"folder_id": str(folder_id), "title": title},
        files={"file": (f"{title}.txt", payload, "text/plain")},
    ).json()


# ---------------------------------------------------------------------------
# System: health + security headers
# ---------------------------------------------------------------------------
def test_health_endpoint(client):
    r = client.get("/api/system/health")
    assert r.status_code == 200
    body = r.json()
    assert body["status"] == "ok"
    assert body["checks"]["database"] == "ok"
    assert body["checks"]["storage"] == "ok"


def test_security_headers_present(client):
    r = client.get("/")
    assert r.headers.get("X-Content-Type-Options") == "nosniff"
    assert r.headers.get("X-Frame-Options") == "DENY"
    assert r.headers.get("Referrer-Policy") == "no-referrer"


# ---------------------------------------------------------------------------
# Share links
# ---------------------------------------------------------------------------
def test_readonly_user_cannot_create_share(client, admin_token, root_folder_id):
    admin = _auth(admin_token)
    doc = _upload(client, admin, root_folder_id, "SharedDoc")
    # A plain registered user has read (public folder) but not write.
    viewer = _register(client, "viewer1")
    r = client.post(f"/api/documents/{doc['id']}/shares", headers=viewer)
    assert r.status_code == 403


def test_share_has_default_expiry_and_atomic_download_limit(client, admin_token, root_folder_id):
    admin = _auth(admin_token)
    doc = _upload(client, admin, root_folder_id, "LimitDoc")
    r = client.post(f"/api/documents/{doc['id']}/shares?max_downloads=1", headers=admin)
    assert r.status_code == 200
    share = r.json()
    # Default 7-day expiry is applied even when expires_days is omitted.
    assert share["expires_at"] is not None

    token = share["token"]
    first = client.get(f"/api/shares/{token}")
    assert first.status_code == 200
    second = client.get(f"/api/shares/{token}")
    assert second.status_code == 410  # limit reached


def test_share_token_not_logged_and_masked_for_others(client, admin_token, root_folder_id):
    admin = _auth(admin_token)
    doc = _upload(client, admin, root_folder_id, "MaskedDoc")
    share = client.post(f"/api/documents/{doc['id']}/shares", headers=admin).json()

    db = db_mod.SessionLocal()
    try:
        details = " ".join(
            row[0] or ""
            for row in db.query(models.AuditLog.details)
            .filter(models.AuditLog.action == "SHARE_CREATE")
            .all()
        )
        assert share["token"] not in details
    finally:
        db.close()

    viewer = _register(client, "viewer2")
    listed = client.get(f"/api/documents/{doc['id']}/shares", headers=viewer).json()
    assert listed, "reader should still see share metadata"
    for entry in listed:
        assert entry["url"] is None
        assert entry["token"] != share["token"]


# ---------------------------------------------------------------------------
# Folder export subtree ACL
# ---------------------------------------------------------------------------
def test_export_excludes_inaccessible_subfolders(client, admin_token, root_folder_id):
    admin = _auth(admin_token)
    private = client.post(
        "/api/folders",
        json={"name": "PrivExport", "parent_id": root_folder_id, "is_public": False},
        headers=admin,
    ).json()
    _upload(client, admin, private["id"], "SecretDoc")
    _upload(client, admin, root_folder_id, "PublicDoc")

    bob = _register(client, "exportbob")
    r = client.get(f"/api/folders/{root_folder_id}/export", headers=bob)
    assert r.status_code == 200
    names = zipfile.ZipFile(io.BytesIO(r.content)).namelist()
    assert any("PublicDoc" in n for n in names)
    assert not any("SecretDoc" in n for n in names)


# ---------------------------------------------------------------------------
# Calendar scoping
# ---------------------------------------------------------------------------
def test_calendar_scoped_to_creator(client):
    bob = _register(client, "calbob")
    r = client.post(
        "/api/calendar",
        json={"title": "bob private meeting", "start_at": "2026-09-01T10:00:00"},
        headers=bob,
    )
    assert r.status_code == 200
    alice = _register(client, "calalice")
    assert client.get("/api/calendar", headers=alice).json() == []
    assert len(client.get("/api/calendar", headers=bob).json()) == 1


# ---------------------------------------------------------------------------
# Workflow guards
# ---------------------------------------------------------------------------
def test_workflow_template_delete_blocked_after_use(client, admin_token, root_folder_id):
    admin = _auth(admin_token)
    doc = _upload(client, admin, root_folder_id, "FlowDoc")
    w = client.post(
        "/api/workflows",
        json={"name": "w1", "steps": [{"name": "review", "assignee_role": "superadmin"}]},
        headers=admin,
    ).json()
    started = client.post(
        f"/api/documents/{doc['id']}/workflows?template_id={w['id']}", headers=admin
    )
    assert started.status_code == 200
    # Used template cannot be deleted (would FK-fail with a 500).
    assert client.delete(f"/api/workflows/{w['id']}", headers=admin).status_code == 409
    # No second concurrent workflow on the same document.
    again = client.post(
        f"/api/documents/{doc['id']}/workflows?template_id={w['id']}", headers=admin
    )
    assert again.status_code == 409


def test_workflow_steps_must_have_assignee(client, admin_token):
    admin = _auth(admin_token)
    r = client.post(
        "/api/workflows",
        json={"name": "bad", "steps": [{"name": "orphan step"}]},
        headers=admin,
    )
    assert r.status_code == 400


# ---------------------------------------------------------------------------
# Retention delete safety
# ---------------------------------------------------------------------------
def test_retention_delete_purges_document_cleanly(client, admin_token, root_folder_id):
    admin = _auth(admin_token)
    doc = _upload(client, admin, root_folder_id, "OldDoc")
    doc_id = doc["id"]

    # Age the document beyond the policy window.
    db = db_mod.SessionLocal()
    try:
        d = db.get(models.Document, doc_id)
        d.created_at = now() - timedelta(days=3650)
        db.commit()
    finally:
        db.close()

    client.post(
        "/api/retention-policies",
        json={"name": "purge", "folder_id": root_folder_id, "years": 1, "action": "delete"},
        headers=admin,
    )
    r = client.post("/api/retention-policies/apply", headers=admin)
    assert r.status_code == 200
    assert r.json()["failed"] == 0

    db = db_mod.SessionLocal()
    try:
        assert db.get(models.Document, doc_id) is None
        assert db.query(models.DocumentVersion).filter_by(document_id=doc_id).count() == 0
    finally:
        db.close()


# ---------------------------------------------------------------------------
# Import folder path validation
# ---------------------------------------------------------------------------
def test_import_folder_requires_configured_root(client, admin_token, tmp_path, monkeypatch):
    admin = _auth(admin_token)
    monkeypatch.setattr(settings, "import_root", "")
    r = client.post(
        "/api/import/folders",
        json={"name": "x", "local_path": str(tmp_path), "target_folder_id": 1},
        headers=admin,
    )
    assert r.status_code == 400  # feature disabled without EDMS_IMPORT_ROOT

    monkeypatch.setattr(settings, "import_root", str(tmp_path))
    outside = tmp_path.parent
    r2 = client.post(
        "/api/import/folders",
        json={"name": "x", "local_path": str(outside), "target_folder_id": 1},
        headers=admin,
    )
    assert r2.status_code == 400  # outside the allowed root

    r3 = client.post(
        "/api/import/folders",
        json={"name": "ok", "local_path": str(tmp_path), "target_folder_id": 1},
        headers=admin,
    )
    assert r3.status_code == 200


def test_import_scan_denied_to_manager(client, admin_token, tmp_path, monkeypatch):
    admin = _auth(admin_token)
    monkeypatch.setattr(settings, "import_root", str(tmp_path))
    imp = client.post(
        "/api/import/folders",
        json={"name": "m", "local_path": str(tmp_path), "target_folder_id": 1},
        headers=admin,
    ).json()
    client.post(
        "/api/users",
        json={"username": "mgr1", "password": "goodpass1", "role": "manager"},
        headers=admin,
    )
    mgr_tok = client.post(
        "/api/auth/login", data={"username": "mgr1", "password": "goodpass1"}
    ).json()["access_token"]
    # Managers must not be able to trigger filesystem scans.
    assert (
        client.post(f"/api/import/folders/{imp['id']}/scan", headers=_auth(mgr_tok)).status_code
        == 403
    )
