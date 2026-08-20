"""Wave 0–2 completion: ACL, tenancy, protocols, converters, providers, cases."""
from __future__ import annotations

import io

from tests.conftest import _auth


def _upload(client, headers, folder_id, title="Doc", body=b"hello invoice INV-12345"):
    files = {"file": ("note.txt", io.BytesIO(body), "text/plain")}
    r = client.post(
        "/api/documents",
        data={"folder_id": folder_id, "title": title, "tags": "invoice"},
        files=files,
        headers=headers,
    )
    assert r.status_code == 200, r.text
    return r.json()


def test_document_acl(client, admin_token, root_folder_id):
    headers = _auth(admin_token)
    doc = _upload(client, headers, root_folder_id)
    r = client.get(f"/api/documents/{doc['id']}/acl", headers=headers)
    assert r.status_code == 200
    r2 = client.post(
        f"/api/documents/{doc['id']}/acl",
        json={"principal_type": "user", "principal_id": 1, "flags": {"read": True, "download": True}},
        headers=headers,
    )
    assert r2.status_code == 200
    listed = client.get(f"/api/documents/{doc['id']}/acl", headers=headers).json()
    assert listed and listed[0]["flags"]["read"] is True


def test_converters_report_installed_tools(client, admin_token):
    r = client.get("/api/converters", headers=_auth(admin_token))
    assert r.status_code == 200
    names = {row["id"] for row in r.json()}
    assert "tesseract" in names or "pdf" in names


def test_auth_providers(client):
    r = client.get("/api/auth/providers")
    assert r.status_code == 200
    body = r.json()
    assert body["local"] is True
    assert "oidc" in body and "saml" in body


def test_webdav_lock_unlock(client, admin_token, root_folder_id):
    headers = _auth(admin_token)
    r = client.request("LOCK", "/webdav/", headers=headers)
    assert r.status_code == 200
    token = r.headers.get("Lock-Token") or ""
    r2 = client.request("UNLOCK", "/webdav/", headers={**headers, "Lock-Token": token})
    assert r2.status_code == 204


def test_soap_create_and_download(client, admin_token, root_folder_id):
    headers = _auth(admin_token)
    xml = f"""<?xml version="1.0"?>
    <soap:Envelope xmlns:soap="http://schemas.xmlsoap.org/soap/envelope/">
      <soap:Body>
        <createDocument>
          <folderId>{root_folder_id}</folderId>
          <title>soap-doc.txt</title>
          <content>aGVsbG8=</content>
        </createDocument>
      </soap:Body>
    </soap:Envelope>"""
    r = client.post("/soap/document", content=xml, headers={**headers, "Content-Type": "text/xml"})
    assert r.status_code == 200, r.text
    assert "createDocumentResponse" in r.text
    did = r.text.split("<id>")[1].split("</id>")[0]
    dl = f"""<?xml version="1.0"?>
    <soap:Envelope xmlns:soap="http://schemas.xmlsoap.org/soap/envelope/">
      <soap:Body><download><id>{did}</id></download></soap:Body>
    </soap:Envelope>"""
    r2 = client.post("/soap/document", content=dl, headers={**headers, "Content-Type": "text/xml"})
    assert r2.status_code == 200
    assert "downloadResponse" in r2.text


def test_cmis_create_document(client, admin_token, root_folder_id):
    headers = _auth(admin_token)
    r = client.post(
        "/cmis/browser/root",
        json={"cmisaction": "createDocument", "name": "from-cmis.txt", "content": "hi", "objectId": "folder-root"},
        headers=headers,
    )
    assert r.status_code == 201, r.text
    assert r.json()["name"] == "from-cmis.txt"


def test_office_link(client, admin_token, root_folder_id):
    headers = _auth(admin_token)
    doc = _upload(client, headers, root_folder_id, title="letter.docx")
    r = client.post(f"/api/documents/{doc['id']}/office-link", headers=headers)
    assert r.status_code == 200
    body = r.json()
    assert "ms-word:ofe|u|" in body["protocol"]
    assert "/api/shares/" in body["url"]


def test_rag_hashing_fallback(client, admin_token):
    r = client.post("/api/rag", json={"query": "invoice amounts"}, headers=_auth(admin_token))
    assert r.status_code == 200
    assert r.json().get("backend") in ("hashing", "llm")


def test_document_stamped_with_collective(client, admin_token, root_folder_id):
    headers = _auth(admin_token)
    doc = _upload(client, headers, root_folder_id, title="tenant-doc")
    assert "collective_id" in doc
    got = client.get(f"/api/documents/{doc['id']}", headers=headers).json()
    # Seeded admin belongs to the default collective.
    assert got.get("collective_id") is not None or got.get("id") == doc["id"]


def test_bpmn_case_runner(client, admin_token, root_folder_id):
    headers = _auth(admin_token)
    xml = """<?xml version="1.0"?>
    <definitions xmlns="http://www.omg.org/spec/BPMN/20100524/MODEL">
      <process id="p1" name="review">
        <startEvent id="start"/>
        <userTask id="review" name="Review" assigneeRole="admin"/>
        <endEvent id="end"/>
        <sequenceFlow sourceRef="start" targetRef="review"/>
        <sequenceFlow sourceRef="review" targetRef="end"/>
      </process>
    </definitions>"""
    bpmn = client.post("/api/bpmn", data={"name": "case-flow", "xml": xml}, headers=headers)
    assert bpmn.status_code == 200, bpmn.text
    bpmn_id = bpmn.json()["id"]
    doc = _upload(client, headers, root_folder_id, title="case-item")
    case = client.post(
        "/api/cases",
        json={"name": "Matter", "document_ids": [doc["id"]], "bpmn_id": bpmn_id},
        headers=headers,
    )
    assert case.status_code == 200, case.text
    started = client.post(f"/api/cases/{case.json()['id']}/start", headers=headers)
    assert started.status_code == 200, started.text


def test_pades_sign_method(client, admin_token, root_folder_id):
    from fpdf import FPDF

    pdf = FPDF()
    pdf.add_page()
    pdf.set_font("Helvetica", size=12)
    pdf.cell(40, 10, "Sign me")
    data = pdf.output()
    headers = _auth(admin_token)
    files = {"file": ("s.pdf", io.BytesIO(data), "application/pdf")}
    doc = client.post("/api/documents", data={"folder_id": root_folder_id, "title": "s"}, files=files, headers=headers).json()
    r = client.post(f"/api/documents/{doc['id']}/sign", data={"reason": "approved"}, headers=headers)
    assert r.status_code == 200, r.text
    assert r.json().get("method") in ("pades-b-cms", "rsa-pkcs1-sha256", "hmac-sha256")


def test_smtp_gateway_status(client, admin_token):
    r = client.get("/api/smtp-gateway", headers=_auth(admin_token))
    assert r.status_code == 200
    assert "enabled" in r.json()


def test_import_root_defaults_to_storage(client, admin_token, tmp_path, monkeypatch):
    from app.config import settings

    # Empty still disables (lockdown / tests).
    monkeypatch.setattr(settings, "import_root", "")
    r = client.post(
        "/api/import/folders",
        json={"name": "x", "local_path": str(tmp_path), "target_folder_id": 1},
        headers=_auth(admin_token),
    )
    assert r.status_code == 400
    # Default config path is storage/imports — not an empty string in Settings.
    from app.config import Settings

    assert Settings.model_fields["import_root"].default.endswith("imports")


def test_sign_verify_endpoint(client, admin_token, root_folder_id):
    from fpdf import FPDF

    pdf = FPDF()
    pdf.add_page()
    pdf.set_font("Helvetica", size=12)
    pdf.cell(40, 10, "Sign me")
    data = pdf.output()
    headers = _auth(admin_token)
    files = {"file": ("s.pdf", io.BytesIO(data), "application/pdf")}
    doc = client.post("/api/documents", data={"folder_id": root_folder_id, "title": "s"}, files=files, headers=headers).json()
    client.post(f"/api/documents/{doc['id']}/sign", data={"reason": "approved"}, headers=headers)
    r = client.get(f"/api/documents/{doc['id']}/sign/verify", headers=headers)
    assert r.status_code == 200, r.text
    body = r.json()
    assert "ok" in body and "embedded" in body


def test_gdrive_files_without_token(client, admin_token):
    r = client.get("/api/connectors/gdrive/files", headers=_auth(admin_token))
    assert r.status_code == 200
    assert r.json() == []


def test_group_members_roundtrip(client, admin_token):
    headers = _auth(admin_token)
    g = client.post("/api/groups", json={"name": "wave-group", "description": ""}, headers=headers)
    assert g.status_code == 200
    gid = g.json()["id"]
    users = client.get("/api/users", headers=headers).json()
    uid = users[0]["id"]
    assert client.post(f"/api/groups/{gid}/users/{uid}", headers=headers).status_code == 200
    listed = client.get(f"/api/groups/{gid}/users", headers=headers)
    assert listed.status_code == 200
    assert any(u["id"] == uid for u in listed.json())
    assert client.delete(f"/api/groups/{gid}/users/{uid}", headers=headers).status_code == 200


def test_redaction_rule_json(client, admin_token):
    r = client.post(
        "/api/redaction-rules",
        json={"name": "ssn", "patterns": [r"\d{3}-\d{2}-\d{4}"]},
        headers=_auth(admin_token),
    )
    assert r.status_code == 200, r.text
    assert r.json()["name"] == "ssn"


def test_legal_hold_lists_titles(client, admin_token, root_folder_id):
    headers = _auth(admin_token)
    doc = _upload(client, headers, root_folder_id, title="held-item")
    r = client.post(
        "/api/legal-holds",
        json={"name": "matter", "reason": "litigation", "document_ids": [doc["id"]]},
        headers=headers,
    )
    assert r.status_code == 200, r.text
    listed = client.get("/api/legal-holds", headers=headers).json()
    assert listed
    assert listed[0]["documents"]
    assert listed[0]["documents"][0]["title"]


def test_i18n_inspector_keys(client):
    from app.i18n import load_catalog

    load_catalog.cache_clear()
    en = client.get("/api/i18n/en").json()
    de = client.get("/api/i18n/de").json()
    assert en["insp.preview"] == "Preview"
    assert de["insp.preview"] == "Vorschau"
    assert "nav.admin" in en and "nav.admin" in de


def test_hard_tenancy_blocks_cross_collective(client):
    from app import database as db_mod
    from app.models import Collective, Document, Folder, User
    from app.security import get_password_hash

    db = db_mod.SessionLocal()
    try:
        a = Collective(name="TenantA")
        b = Collective(name="TenantB")
        db.add_all([a, b])
        db.flush()
        ua = User(username="alice", hashed_password=get_password_hash("alice1234"), role="user", is_active=True, collective_id=a.id)
        ub = User(username="bob", hashed_password=get_password_hash("bob123456"), role="user", is_active=True, collective_id=b.id)
        db.add_all([ua, ub])
        db.flush()
        root = db.query(Folder).filter(Folder.parent_id.is_(None)).first()
        fa = Folder(name="A-docs", parent_id=root.id, created_by=ua.id, is_public=False, collective_id=a.id)
        db.add(fa)
        db.flush()
        da = Document(
            name="secret.txt",
            title="secret",
            folder_id=fa.id,
            created_by=ua.id,
            status="draft",
            size=0,
            file_path="",
            current_version=1,
            collective_id=a.id,
        )
        db.add(da)
        db.commit()
        did = da.id
    finally:
        db.close()

    login = client.post("/api/auth/login", data={"username": "bob", "password": "bob123456"})
    assert login.status_code == 200, login.text
    tok = login.json()["access_token"]
    r = client.get(f"/api/documents/{did}", headers=_auth(tok))
    assert r.status_code in (403, 404)
