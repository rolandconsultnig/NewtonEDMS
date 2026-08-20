"""NewtonEDMS fusion tests: query language, contacts, JOEX, TOTP, bookmarks, uploads."""
from __future__ import annotations

import zipfile
from datetime import datetime, timedelta
from io import BytesIO

from app.querylang import parse_query
from app.totp import generate_secret, totp, verify_totp


def _auth(token: str) -> dict:
    return {"Authorization": f"Bearer {token}"}


def _upload(client, token, folder_id, name="note.txt", body=b"Invoice from Acme Corp 2026-08-14", **data):
    payload = {"folder_id": str(folder_id), "title": name, **data}
    return client.post(
        "/api/documents",
        headers=_auth(token),
        data=payload,
        files={"file": (name, body, "text/plain")},
    )


def test_product_branding(client):
    r = client.get("/docs")
    assert r.status_code == 200
    openapi = client.get("/openapi.json").json()
    assert openapi["info"]["title"] == "NewtonEDMS"


def test_query_language_parser():
    p = parse_query('tag:invoice correspondent:acme due:overdue "purchase order"')
    assert "invoice" in p.filters["tags"]
    assert p.filters["correspondent"] == "acme"
    assert p.filters["due"] == "overdue"
    assert "purchase order" in p.fulltext


def test_contacts_and_query(client, admin_token, root_folder_id):
    headers = _auth(admin_token)
    c = client.post(
        "/api/contacts",
        headers=headers,
        json={"name": "Acme Corp", "kind": "correspondent", "organization": "Acme"},
    )
    assert c.status_code == 200, c.text
    cid = c.json()["id"]

    up = _upload(client, admin_token, root_folder_id, tags="invoice")
    assert up.status_code == 200, up.text
    doc_id = up.json()["id"]
    client.put(
        f"/api/documents/{doc_id}",
        headers=headers,
        data={"correspondent_id": str(cid), "due_date": "2020-01-01", "notes": "old invoice"},
    )

    found = client.get("/api/query?q=tag:invoice correspondent:Acme due:overdue", headers=headers)
    assert found.status_code == 200
    assert any(d["id"] == doc_id for d in found.json())


def test_bookmarks_and_custom_fields(client, admin_token, root_folder_id):
    headers = _auth(admin_token)
    bm = client.post("/api/bookmarks", headers=headers, json={"name": "invoices", "query": "tag:invoice"})
    assert bm.status_code == 200
    listed = client.get("/api/bookmarks", headers=headers).json()
    assert listed[0]["query"] == "tag:invoice"

    field = client.post(
        "/api/custom-fields",
        headers=headers,
        json={"name": "amount", "ftype": "money"},
    )
    assert field.status_code == 200
    doc = _upload(client, admin_token, root_folder_id).json()
    put = client.put(
        f"/api/documents/{doc['id']}/fields",
        headers=headers,
        json=[{"field_id": field.json()["id"], "value": "42.00"}],
    )
    assert put.status_code == 200
    vals = client.get(f"/api/documents/{doc['id']}/fields", headers=headers).json()
    assert vals[0]["value"] == "42.00"


def test_joex_extracts_text_and_hash(client, admin_token, root_folder_id):
    up = _upload(client, admin_token, root_folder_id, body=b"The invoice and the contract")
    assert up.status_code == 200
    doc = up.json()
    # joex_inline is on in tests, so processing should have finished.
    got = client.get(f"/api/documents/{doc['id']}", headers=_auth(admin_token)).json()
    assert got["content_hash"]
    assert got["processing_status"] == "done"
    text = client.get(f"/api/documents/{doc['id']}/text", headers=_auth(admin_token)).json()
    assert "invoice" in (text["text"] or "").lower() or "invoice" in (got.get("tags") or "").lower()


def test_zip_extraction_creates_attachments(client, admin_token, root_folder_id):
    buf = BytesIO()
    with zipfile.ZipFile(buf, "w") as zf:
        zf.writestr("inner.txt", "hello from zip")
    buf.seek(0)
    up = client.post(
        "/api/documents",
        headers=_auth(admin_token),
        data={"folder_id": str(root_folder_id), "title": "bundle"},
        files={"file": ("bundle.zip", buf.getvalue(), "application/zip")},
    )
    assert up.status_code == 200, up.text
    atts = client.get(f"/api/documents/{up.json()['id']}/attachments", headers=_auth(admin_token)).json()
    assert any(a["name"] == "inner.txt" for a in atts)


def test_duplicate_detection(client, admin_token, root_folder_id):
    body = b"identical payload for hashing"
    a = _upload(client, admin_token, root_folder_id, name="a.txt", body=body).json()
    b = _upload(client, admin_token, root_folder_id, name="b.txt", body=body).json()
    got = client.get(f"/api/documents/{b['id']}", headers=_auth(admin_token)).json()
    assert got["duplicate_of"] == a["id"]


def test_merge_and_bulk_edit(client, admin_token, root_folder_id):
    headers = _auth(admin_token)
    a = _upload(client, admin_token, root_folder_id, name="one.txt", body=b"one").json()
    b = _upload(client, admin_token, root_folder_id, name="two.txt", body=b"two").json()
    merged = client.post(
        "/api/documents/merge",
        headers=headers,
        json={"ids": [a["id"], b["id"]], "title": "Both"},
    )
    assert merged.status_code == 200, merged.text
    assert merged.json()["title"] == "Both"
    bulk = client.post(
        "/api/documents/bulk-edit",
        headers=headers,
        json={"ids": [a["id"], b["id"]], "tags": "bulk", "status": "review"},
    )
    assert bulk.status_code == 200
    assert bulk.json()["updated"] == 2


def test_anonymous_upload_url(client, admin_token, root_folder_id):
    headers = _auth(admin_token)
    created = client.post(
        "/api/open-uploads",
        headers=headers,
        json={"name": "inbox", "folder_id": root_folder_id, "tags": "scan"},
    )
    assert created.status_code == 200, created.text
    token = created.json()["token"]
    page = client.get(f"/u/{token}")
    assert page.status_code == 200
    assert b"NewtonEDMS" in page.content
    posted = client.post(f"/api/open/{token}", files={"file": ("scan.txt", b"scanned", "text/plain")})
    assert posted.status_code == 200, posted.text
    docs = client.get(f"/api/documents?folder_id={root_folder_id}", headers=headers).json()
    assert any(d["source"] == "anonymous" for d in docs)


def test_totp_roundtrip(client, admin_token):
    headers = _auth(admin_token)
    setup = client.post("/api/auth/totp/setup", headers=headers)
    assert setup.status_code == 200
    secret = setup.json()["secret"]
    code = totp(secret)
    enable = client.post("/api/auth/totp/enable", headers=headers, data={"code": code})
    assert enable.status_code == 200, enable.text
    # Login without TOTP is rejected
    denied = client.post("/api/auth/login", data={"username": "admin", "password": "admin123"})
    assert denied.status_code == 403
    ok = client.post(
        "/api/auth/login",
        data={"username": "admin", "password": "admin123"},
        headers={"X-TOTP": totp(secret)},
    )
    assert ok.status_code == 200


def test_totp_helper_accepts_current_window():
    secret = generate_secret()
    assert verify_totp(secret, totp(secret))


def test_password_share(client, admin_token, root_folder_id):
    headers = _auth(admin_token)
    doc = _upload(client, admin_token, root_folder_id).json()
    share = client.post(
        f"/api/documents/{doc['id']}/shares?password=secret12&name=partner",
        headers=headers,
    )
    assert share.status_code == 200
    assert share.json()["password_protected"] is True
    token = share.json()["token"]
    blocked = client.get(f"/api/shares/{token}")
    assert blocked.status_code == 401
    allowed = client.get(f"/api/shares/{token}?password=secret12")
    assert allowed.status_code == 200


def test_dashboard_and_jobs(client, admin_token, root_folder_id):
    _upload(client, admin_token, root_folder_id)
    home = client.get("/api/dashboards/home", headers=_auth(admin_token))
    assert home.status_code == 200
    assert "recent" in home.json()
    jobs = client.get("/api/jobs", headers=_auth(admin_token))
    assert jobs.status_code == 200
    assert len(jobs.json()) >= 1


def test_collectives_and_tags_seeded(client, admin_token):
    headers = _auth(admin_token)
    cols = client.get("/api/collectives", headers=headers).json()
    assert any(c["name"] == "Newton" for c in cols)
    tags = client.get("/api/tags", headers=headers).json()
    assert any(t["name"] == "invoice" for t in tags)


def test_due_notification_job(client, admin_token, root_folder_id):
    from app.joex import notify_due_items

    headers = _auth(admin_token)
    doc = _upload(client, admin_token, root_folder_id).json()
    past = (datetime.utcnow() - timedelta(days=2)).strftime("%Y-%m-%d")
    client.put(f"/api/documents/{doc['id']}", headers=headers, data={"due_date": past})
    created = notify_due_items()
    assert created >= 1
    notifs = client.get("/api/notifications", headers=headers).json()
    assert any("overdue" in n["message"].lower() for n in notifs)
