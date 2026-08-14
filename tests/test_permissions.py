"""Document visibility filtering (the former list_documents N+1 path)."""
from __future__ import annotations

from app import database as db_mod
from app.models import Document


def _auth(token: str) -> dict:
    return {"Authorization": f"Bearer {token}"}


def _upload(client, headers, folder_id, title, payload=b"x"):
    return client.post(
        "/api/documents",
        headers=headers,
        data={"folder_id": str(folder_id), "title": title},
        files={"file": (f"{title}.txt", payload, "text/plain")},
    ).json()


def _register(client, username, password="pw12345"):
    token = client.post(
        "/api/auth/register", data={"username": username, "password": password}
    ).json()["access_token"]
    headers = _auth(token)
    uid = client.get("/api/auth/me", headers=headers).json()["id"]
    return headers, uid


def test_user_sees_only_visible_documents(client, admin_token, root_folder_id):
    admin = _auth(admin_token)

    pf1 = client.post(
        "/api/folders",
        json={"name": "Private1", "parent_id": root_folder_id, "is_public": False},
        headers=admin,
    ).json()
    pf2 = client.post(
        "/api/folders",
        json={"name": "Private2", "parent_id": root_folder_id, "is_public": False},
        headers=admin,
    ).json()

    _upload(client, admin, root_folder_id, "PublicDoc")     # public folder
    _upload(client, admin, pf1["id"], "PrivateDoc1")        # granted folder
    _upload(client, admin, pf2["id"], "PrivateDoc2")        # ungranted folder

    alice, alice_id = _register(client, "alice")

    # Grant alice read on PF1 only.
    client.post(
        f"/api/folders/{pf1['id']}/permissions",
        headers=admin,
        data={"principal_type": "user", "principal_id": str(alice_id), "can_read": "true"},
    )

    seen = {d["title"] for d in client.get("/api/documents", headers=alice).json()}
    assert "PublicDoc" in seen          # public folder
    assert "PrivateDoc1" in seen        # granted folder
    assert "PrivateDoc2" not in seen    # ungranted private folder

    # Grant read on PF2 -> its document becomes visible.
    client.post(
        f"/api/folders/{pf2['id']}/permissions",
        headers=admin,
        data={"principal_type": "user", "principal_id": str(alice_id), "can_read": "true"},
    )
    seen_after = {d["title"] for d in client.get("/api/documents", headers=alice).json()}
    assert "PrivateDoc2" in seen_after


def test_own_document_visible_without_folder_read(client, admin_token, root_folder_id):
    """A document the user owns is visible even if its folder is not readable to them."""
    admin = _auth(admin_token)
    private = client.post(
        "/api/folders",
        json={"name": "OwnOnly", "parent_id": root_folder_id, "is_public": False},
        headers=admin,
    ).json()
    alice, alice_id = _register(client, "owner_alice")

    # Insert a doc owned by alice in a folder she cannot read (no file needed for listing).
    db = db_mod.SessionLocal()
    try:
        db.add(Document(
            name="owned.txt", title="OwnedByAlice", folder_id=private["id"],
            file_path="/tmp/owned.txt", created_by=alice_id,
        ))
        db.commit()
    finally:
        db.close()

    seen = {d["title"] for d in client.get("/api/documents", headers=alice).json()}
    assert "OwnedByAlice" in seen


def test_admin_sees_all_documents(client, admin_token, root_folder_id):
    admin = _auth(admin_token)
    private = client.post(
        "/api/folders",
        json={"name": "PrivateAdm", "parent_id": root_folder_id, "is_public": False},
        headers=admin,
    ).json()
    _upload(client, admin, private["id"], "Hidden")

    seen = {d["title"] for d in client.get("/api/documents", headers=admin).json()}
    assert "Hidden" in seen  # admins bypass folder visibility filtering


def test_visibility_filter_respects_folder_scope(client, admin_token, root_folder_id):
    admin = _auth(admin_token)
    private = client.post(
        "/api/folders",
        json={"name": "Scoped", "parent_id": root_folder_id, "is_public": False},
        headers=admin,
    ).json()
    _upload(client, admin, private["id"], "ScopedDoc")

    bob, _ = _register(client, "bob")
    scoped = client.get(f"/api/documents?folder_id={private['id']}", headers=bob).json()
    assert scoped == []
