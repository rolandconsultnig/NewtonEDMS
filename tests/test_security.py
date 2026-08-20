"""Authentication, RBAC, and hardening (rate-limit / upload-policy) tests."""
from __future__ import annotations

from app.config import settings
from app.limiter import limiter


def _auth(token: str) -> dict:
    return {"Authorization": f"Bearer {token}"}


def login(client, username="admin", password="admin123"):
    return client.post("/api/auth/login", data={"username": username, "password": password})


# ---------------------------------------------------------------------------
# Authentication
# ---------------------------------------------------------------------------
def test_login_success_returns_token(client):
    resp = login(client)
    assert resp.status_code == 200
    body = resp.json()
    assert body["token_type"] == "bearer"
    assert body["access_token"]


def test_login_wrong_password_rejected(client):
    assert login(client, password="nope").status_code == 401


def test_missing_token_is_unauthorized(client):
    assert client.get("/api/auth/me").status_code == 401


def test_session_probe_is_ok_without_cookie(client):
    resp = client.get("/api/auth/session")
    assert resp.status_code == 200
    assert resp.json() == {"user": None}


def test_session_probe_returns_user_when_logged_in(client):
    login(client)
    resp = client.get("/api/auth/session")
    assert resp.status_code == 200
    assert resp.json()["user"]["username"] == "admin"


def test_favicon_is_served(client):
    resp = client.get("/favicon.ico")
    assert resp.status_code == 200
    assert "image/svg" in resp.headers.get("content-type", "")


def test_invalid_token_is_unauthorized(client):
    resp = client.get("/api/auth/me", headers={"Authorization": "Bearer not-a-jwt"})
    assert resp.status_code == 401


def test_me_returns_current_user(client, admin_token):
    me = client.get("/api/auth/me", headers=_auth(admin_token)).json()
    assert me["username"] == "admin"
    assert me["role"] == "superadmin"


# ---------------------------------------------------------------------------
# Cookie auth + revocation
# ---------------------------------------------------------------------------
def test_login_sets_httponly_cookie_used_for_auth(client):
    r = client.post("/api/auth/login", data={"username": "admin", "password": "admin123"})
    assert r.status_code == 200
    assert "newton_token" in r.cookies
    # No Authorization header -> the cookie must authenticate the request.
    me = client.get("/api/auth/me")
    assert me.status_code == 200
    assert me.json()["username"] == "admin"


def test_login_remember_extends_cookie(client):
    r = client.post(
        "/api/auth/login",
        data={"username": "admin", "password": "admin123", "remember": "1"},
    )
    assert r.status_code == 200
    header = (r.headers.get("set-cookie") or "").lower()
    assert "max-age=2592000" in header


def test_logout_revokes_token_and_clears_cookie(client):
    r = client.post("/api/auth/login", data={"username": "admin", "password": "admin123"})
    token = r.json()["access_token"]

    # Authenticated before logout (header form).
    assert client.get("/api/auth/me", headers=_auth(token)).status_code == 200

    assert client.post("/api/auth/logout").status_code == 200

    # The old token is revoked server-side, even when presented via header.
    assert client.get("/api/auth/me", headers=_auth(token)).status_code == 401
    # And the cookie is cleared, so no header/cookie -> 401.
    assert client.get("/api/auth/me").status_code == 401


def test_second_login_still_works_after_logout(client):
    client.post("/api/auth/login", data={"username": "admin", "password": "admin123"})
    client.post("/api/auth/logout")
    # A fresh login mints a new (non-revoked) token.
    r = client.post("/api/auth/login", data={"username": "admin", "password": "admin123"})
    assert r.status_code == 200
    assert client.get("/api/auth/me").status_code == 200


# ---------------------------------------------------------------------------
# RBAC
# ---------------------------------------------------------------------------
def test_plain_user_cannot_list_users(client):
    # The public register endpoint always creates a "user" role.
    resp = client.post("/api/auth/register", data={"username": "alice", "password": "alicepw1"})
    assert resp.status_code == 200
    token = resp.json()["access_token"]

    forbidden = client.get("/api/users", headers=_auth(token))
    assert forbidden.status_code == 403


def test_admin_can_list_users(client, admin_token):
    resp = client.get("/api/users", headers=_auth(admin_token))
    assert resp.status_code == 200
    assert any(u["username"] == "admin" for u in resp.json())


def test_user_cannot_delete_other_users(client, admin_token):
    client.post(
        "/api/users",
        json={"username": "bob", "password": "bobpw123", "role": "user"},
        headers=_auth(admin_token),
    )
    bob_token = login(client, "bob", "bobpw123").json()["access_token"]
    admin_id = client.get("/api/auth/me", headers=_auth(admin_token)).json()["id"]
    # bob (role=user) is not even allowed past require_role -> 403
    resp = client.delete(f"/api/users/{admin_id}", headers=_auth(bob_token))
    assert resp.status_code == 403


# ---------------------------------------------------------------------------
# Deactivation regression (login used to silently reactivate users)
# ---------------------------------------------------------------------------
def test_deactivated_user_cannot_login(client, admin_token):
    client.post(
        "/api/users",
        json={"username": "carol", "password": "carolpw1", "role": "user"},
        headers=_auth(admin_token),
    )
    assert login(client, "carol", "carolpw1").status_code == 200

    users = client.get("/api/users", headers=_auth(admin_token)).json()
    carol = next(u for u in users if u["username"] == "carol")
    client.put(f"/api/users/{carol['id']}", json={"is_active": False}, headers=_auth(admin_token))

    # Correct password, but account is suspended -> must stay rejected.
    assert login(client, "carol", "carolpw1").status_code == 401


# ---------------------------------------------------------------------------
# Rate limiting on login
# ---------------------------------------------------------------------------
def test_login_rate_limit_returns_429(client, monkeypatch):
    monkeypatch.setattr(settings, "login_rate_limit", "2/minute")
    limiter.reset()

    assert login(client, password="bad").status_code == 401
    assert login(client, password="bad").status_code == 401
    # Third attempt within the window is throttled.
    assert login(client, password="bad").status_code == 429


# ---------------------------------------------------------------------------
# Upload policy: size cap + blocked extensions
# ---------------------------------------------------------------------------
def test_blocked_extension_rejected(client, admin_token, root_folder_id):
    resp = client.post(
        "/api/documents",
        headers=_auth(admin_token),
        data={"folder_id": str(root_folder_id), "title": "evil"},
        files={"file": ("evil.exe", b"MZ", "application/octet-stream")},
    )
    assert resp.status_code == 400


def test_oversized_upload_rejected(client, admin_token, root_folder_id, monkeypatch):
    monkeypatch.setattr(settings, "max_upload_bytes", 16)
    payload = b"x" * 256
    resp = client.post(
        "/api/documents",
        headers=_auth(admin_token),
        data={"folder_id": str(root_folder_id), "title": "big"},
        files={"file": ("big.txt", payload, "text/plain")},
    )
    assert resp.status_code == 413


def test_oversized_upload_leaves_no_document_row(client, admin_token, root_folder_id, monkeypatch):
    monkeypatch.setattr(settings, "max_upload_bytes", 16)
    before = len(client.get("/api/documents", headers=_auth(admin_token)).json())
    client.post(
        "/api/documents",
        headers=_auth(admin_token),
        data={"folder_id": str(root_folder_id), "title": "big"},
        files={"file": ("big.txt", b"x" * 256, "text/plain")},
    )
    after = len(client.get("/api/documents", headers=_auth(admin_token)).json())
    assert before == after  # no orphan document row
