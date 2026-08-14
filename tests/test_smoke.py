"""End-to-end happy path, run against the isolated in-memory test database."""
from __future__ import annotations


def _auth(token: str) -> dict:
    return {"Authorization": f"Bearer {token}"}


def test_document_lifecycle(client, admin_token, root_folder_id):
    headers = _auth(admin_token)

    # Upload
    upload = client.post(
        "/api/documents",
        headers=headers,
        data={
            "folder_id": str(root_folder_id),
            "title": "Hello Doc",
            "tags": "demo,test",
            "metadata": '{"project": "NewEDMS"}',
        },
        files={"file": ("hello.txt", b"Hello NewEDMS", "text/plain")},
    )
    assert upload.status_code == 200, upload.text
    doc = upload.json()
    assert doc["current_version"] == 1
    doc_id = doc["id"]

    # Read back
    got = client.get(f"/api/documents/{doc_id}", headers=headers)
    assert got.status_code == 200
    assert got.json()["title"] == "Hello Doc"

    # Search (this exercises the previously-broken metadata cast filter)
    results = client.get("/api/documents?search=Hello", headers=headers)
    assert results.status_code == 200
    assert any(d["id"] == doc_id for d in results.json())

    # Add a version
    v2 = client.post(
        f"/api/documents/{doc_id}/versions",
        headers=headers,
        data={"comment": "second"},
        files={"file": ("hello.txt", b"Hello v2", "text/plain")},
    )
    assert v2.status_code == 200
    assert v2.json()["current_version"] == 2

    versions = client.get(f"/api/documents/{doc_id}/versions", headers=headers).json()
    assert len(versions) == 2

    # Download
    dl = client.get(f"/api/documents/{doc_id}/download", headers=headers)
    assert dl.status_code == 200
    assert dl.content == b"Hello v2"

    # Audit trail captured the activity
    logs = client.get("/api/audit", headers=headers).json()
    actions = {entry["action"] for entry in logs}
    assert {"DOCUMENT_CREATE", "VERSION_CREATE"}.issubset(actions)

    # Workflow: advance draft -> review
    upd = client.put(
        f"/api/documents/{doc_id}",
        headers=headers,
        data={"status": "review"},
    )
    assert upd.status_code == 200
    assert upd.json()["status"] == "review"


def test_checkout_checkin_cycle(client, admin_token, root_folder_id):
    headers = _auth(admin_token)
    doc = client.post(
        "/api/documents",
        headers=headers,
        data={"folder_id": str(root_folder_id), "title": "Locked"},
        files={"file": ("a.txt", b"a", "text/plain")},
    ).json()

    assert client.post(f"/api/documents/{doc['id']}/checkout", headers=headers).status_code == 200
    again = client.post(f"/api/documents/{doc['id']}/checkout", headers=headers)
    assert again.status_code == 400  # already checked out
    assert client.post(f"/api/documents/{doc['id']}/checkin", headers=headers).status_code == 200


def test_download_specific_version(client, admin_token, root_folder_id):
    headers = _auth(admin_token)
    doc = client.post(
        "/api/documents",
        headers=headers,
        data={"folder_id": str(root_folder_id), "title": "Versioned"},
        files={"file": ("v.txt", b"version one", "text/plain")},
    ).json()
    client.post(
        f"/api/documents/{doc['id']}/versions",
        headers=headers,
        data={"comment": "second"},
        files={"file": ("v.txt", b"version two", "text/plain")},
    )

    # Default (no ?v=) returns the current version.
    current = client.get(f"/api/documents/{doc['id']}/download", headers=headers)
    assert current.status_code == 200
    assert current.content == b"version two"

    # ?v=1 returns the historical version, with a versioned filename.
    v1 = client.get(f"/api/documents/{doc['id']}/download?v=1", headers=headers)
    assert v1.status_code == 200
    assert v1.content == b"version one"
    assert "v1" in v1.headers["content-disposition"]

    # Unknown version -> 404.
    assert client.get(f"/api/documents/{doc['id']}/download?v=99", headers=headers).status_code == 404
