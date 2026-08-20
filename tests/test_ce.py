"""Community-parity: trash, clipboard, 24-bit ACL, parametric search, messages."""
from tests.conftest import _auth


def _upload(client, headers, folder_id, name="note.txt", body=b"hello"):
    return client.post(
        "/api/documents",
        headers=headers,
        data={"folder_id": str(folder_id), "title": name},
        files={"file": (name, body, "text/plain")},
    ).json()


def test_trash_restore_and_permanent_purge(client, admin_token, root_folder_id):
    headers = _auth(admin_token)
    doc = _upload(client, headers, root_folder_id, "trashed.txt")
    doc_id = doc["id"]
    assert client.delete(f"/api/documents/{doc_id}", headers=headers).status_code == 200
    assert client.get(f"/api/documents/{doc_id}", headers=headers).status_code == 404
    trash = client.get("/api/trash/documents", headers=headers).json()
    assert any(d["id"] == doc_id for d in trash)
    assert client.post(f"/api/trash/documents/{doc_id}/restore", headers=headers).status_code == 200
    assert client.get(f"/api/documents/{doc_id}", headers=headers).status_code == 200
    client.delete(f"/api/documents/{doc_id}", headers=headers)
    assert client.delete(f"/api/trash/documents/{doc_id}", headers=headers).status_code == 200
    assert client.get("/api/trash/documents", headers=headers).json() == []


def test_copy_move_and_alias(client, admin_token, root_folder_id):
    headers = _auth(admin_token)
    child = client.post(
        "/api/folders",
        headers=headers,
        json={"name": "dest", "parent_id": root_folder_id},
    ).json()
    doc = _upload(client, headers, root_folder_id)
    copied = client.post(
        "/api/documents/copy",
        headers=headers,
        json={"ids": [doc["id"]], "target_folder_id": child["id"], "as_alias": False},
    )
    assert copied.status_code == 200
    assert copied.json()["ids"]
    alias = client.post(
        "/api/documents/copy",
        headers=headers,
        json={"ids": [doc["id"]], "target_folder_id": child["id"], "as_alias": True},
    )
    assert alias.status_code == 200
    moved = client.post(
        "/api/documents/move",
        headers=headers,
        json={"ids": [doc["id"]], "target_folder_id": child["id"]},
    )
    assert moved.status_code == 200
    got = client.get(f"/api/documents/{doc['id']}", headers=headers).json()
    assert got["folder_id"] == child["id"]


def test_acl_bits_and_parametric(client, admin_token, root_folder_id):
    headers = _auth(admin_token)
    flags = {"read": True, "preview": True, "write": True, "download": True, "security": True}
    r = client.post(
        f"/api/folders/{root_folder_id}/acl",
        headers=headers,
        json={"principal_type": "user", "principal_id": 1, "flags": flags},
    )
    assert r.status_code == 200
    acl = client.get(f"/api/folders/{root_folder_id}/acl", headers=headers).json()
    assert acl and acl[0]["flags"]["read"] is True
    bits = client.get("/api/acl/bits", headers=headers).json()
    assert "download" in bits or "read" in str(bits)
    _upload(client, headers, root_folder_id, "locked.txt")
    found = client.post("/api/search/parametric", headers=headers, json={"status": "draft"})
    assert found.status_code == 200
    assert isinstance(found.json(), list)


def test_messages_stars_and_webdav_options(client, admin_token, root_folder_id):
    headers = _auth(admin_token)
    users = client.get("/api/users", headers=headers).json()
    to_id = users[0]["id"]
    r = client.post(
        "/api/messages",
        headers=headers,
        json={"to_id": to_id, "subject": "hi", "body": "there"},
    )
    assert r.status_code == 200
    inbox = client.get("/api/messages", headers=headers).json()
    assert any(m["subject"] == "hi" for m in inbox)
    doc = _upload(client, headers, root_folder_id)
    star = client.post(
        "/api/stars",
        headers=headers,
        json={"kind": "document", "resource_id": doc["id"], "name": "starred"},
    )
    assert star.status_code == 200
    bms = client.get("/api/bookmarks", headers=headers).json()
    assert any(b.get("kind") == "document" for b in bms)
    opt = client.options("/webdav/")
    assert opt.status_code == 200
    assert "DAV" in opt.headers
    cmis = client.get("/cmis/browser", headers=headers)
    assert cmis.status_code == 200
