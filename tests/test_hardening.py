"""Batch-2 hardening: password policy, role validation, register rate limit,
FK enforcement, and safe delete paths."""
import pytest
from sqlalchemy.exc import IntegrityError

from app import database as db_mod
from app import models
from app.config import settings
from app.limiter import limiter


def _auth(token):
    return {"Authorization": f"Bearer {token}"}


def _db():
    return db_mod.SessionLocal()


# ---------------------------------------------------------------------------
# Password policy
# ---------------------------------------------------------------------------
def test_register_rejects_short_password(client):
    r = client.post("/api/auth/register", data={"username": "shorty", "password": "ab1"})
    assert r.status_code == 400
    assert "at least" in r.json()["detail"]


def test_register_rejects_password_without_digit(client):
    r = client.post("/api/auth/register", data={"username": "nodigit", "password": "onlyletters"})
    assert r.status_code == 400


def test_register_accepts_strong_password(client):
    r = client.post("/api/auth/register", data={"username": "stronguser", "password": "strong1pw"})
    assert r.status_code == 200


def test_create_user_rejects_weak_password(client, admin_token):
    r = client.post(
        "/api/users",
        json={"username": "weakpw", "password": "123", "role": "user"},
        headers=_auth(admin_token),
    )
    assert r.status_code == 400


# ---------------------------------------------------------------------------
# Role validation
# ---------------------------------------------------------------------------
def test_create_user_rejects_invalid_role(client, admin_token):
    r = client.post(
        "/api/users",
        json={"username": "badrole", "password": "goodpass1", "role": "banana"},
        headers=_auth(admin_token),
    )
    assert r.status_code == 422  # Literal validation


def test_create_user_accepts_valid_role(client, admin_token):
    r = client.post(
        "/api/users",
        json={"username": "manager1", "password": "goodpass1", "role": "manager"},
        headers=_auth(admin_token),
    )
    assert r.status_code == 200
    assert r.json()["role"] == "manager"


def test_update_user_rejects_invalid_role(client, admin_token):
    headers = _auth(admin_token)
    uid = client.post(
        "/api/users",
        json={"username": "manager2", "password": "goodpass1", "role": "manager"},
        headers=headers,
    ).json()["id"]
    r = client.put(f"/api/users/{uid}", json={"role": "wizard"}, headers=headers)
    assert r.status_code == 422


# ---------------------------------------------------------------------------
# Register rate limit
# ---------------------------------------------------------------------------
def test_register_rate_limit_returns_429(client, monkeypatch):
    monkeypatch.setattr(settings, "register_rate_limit", "2/minute")
    limiter.reset()
    ok = client.post("/api/auth/register", data={"username": "rl1", "password": "goodpass1"})
    assert ok.status_code == 200
    ok2 = client.post("/api/auth/register", data={"username": "rl2", "password": "goodpass1"})
    assert ok2.status_code == 200
    third = client.post("/api/auth/register", data={"username": "rl3", "password": "goodpass1"})
    assert third.status_code == 429


# ---------------------------------------------------------------------------
# FK enforcement
# ---------------------------------------------------------------------------
def test_sqlite_foreign_keys_are_enforced(client):
    db = _db()
    try:
        db.add(models.Document(
            name="ghost.txt", title="Ghost", folder_id=999999,
            file_path="/tmp/ghost.txt", created_by=1,
        ))
        with pytest.raises(IntegrityError):
            db.commit()
        db.rollback()
    finally:
        db.close()


# ---------------------------------------------------------------------------
# delete_document purges dependents
# ---------------------------------------------------------------------------
def test_delete_document_purges_versions_and_comments(client, admin_token, root_folder_id):
    headers = _auth(admin_token)
    doc = client.post(
        "/api/documents",
        headers=headers,
        data={"folder_id": str(root_folder_id), "title": "Doomed"},
        files={"file": ("doomed.txt", b"bye", "text/plain")},
    ).json()
    doc_id = doc["id"]

    db = _db()
    try:
        db.add(models.Comment(document_id=doc_id, user_id=1, text="note"))
        db.commit()
    finally:
        db.close()

    assert client.delete(f"/api/documents/{doc_id}", headers=headers).status_code == 200

    db = _db()
    try:
        assert db.query(models.DocumentVersion).filter_by(document_id=doc_id).count() == 0
        assert db.query(models.Comment).filter_by(document_id=doc_id).count() == 0
    finally:
        db.close()


# ---------------------------------------------------------------------------
# delete_user safety
# ---------------------------------------------------------------------------
def test_delete_user_blocked_when_owns_content(client, admin_token, root_folder_id):
    headers = _auth(admin_token)
    r = client.post(
        "/api/users",
        json={"username": "owner1", "password": "goodpass1", "role": "user"},
        headers=headers,
    )
    uid = r.json()["id"]

    db = _db()
    try:
        db.add(models.Document(
            name="owned.txt", title="Owned", folder_id=root_folder_id,
            file_path="/tmp/owned.txt", created_by=uid,
        ))
        db.commit()
    finally:
        db.close()

    resp = client.delete(f"/api/users/{uid}", headers=headers)
    assert resp.status_code == 409
    assert "deactivate" in resp.json()["detail"]


def test_delete_user_cleans_auxiliary_rows(client, admin_token):
    headers = _auth(admin_token)
    r = client.post(
        "/api/users",
        json={"username": "temp1", "password": "goodpass1", "role": "user"},
        headers=headers,
    )
    uid = r.json()["id"]
    # Generate an audit row + notification + comment for the user.
    client.post("/api/auth/login", data={"username": "temp1", "password": "goodpass1"})
    db = _db()
    try:
        db.add(models.Notification(user_id=uid, message="hello"))
        db.commit()
    finally:
        db.close()

    assert client.delete(f"/api/users/{uid}", headers=headers).status_code == 200

    db = _db()
    try:
        assert db.get(models.User, uid) is None
        assert db.query(models.Notification).filter_by(user_id=uid).count() == 0
        # Audit trail survives, with attribution detached.
        orphaned = db.query(models.AuditLog).filter_by(user_id=uid).count()
        assert orphaned == 0
    finally:
        db.close()
    # Deleted user can no longer authenticate.
    assert client.post(
        "/api/auth/login", data={"username": "temp1", "password": "goodpass1"}
    ).status_code == 401


def test_delete_group_removes_its_permissions(client, admin_token, root_folder_id):
    headers = _auth(admin_token)
    g = client.post("/api/groups", json={"name": "tmpgroup"}, headers=headers).json()
    client.post(
        f"/api/folders/{root_folder_id}/permissions",
        headers=headers,
        data={"principal_type": "group", "principal_id": str(g["id"]), "can_read": "true"},
    )
    assert client.delete(f"/api/groups/{g['id']}", headers=headers).status_code == 200

    db = _db()
    try:
        stale = (
            db.query(models.Permission)
            .filter_by(principal_type="group", principal_id=g["id"])
            .count()
        )
        assert stale == 0
    finally:
        db.close()
