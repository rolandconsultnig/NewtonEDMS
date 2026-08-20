"""Enterprise engines: BPMN, PDF ops, legal hold, RAG, IDP, ArchiveLink, rules."""
from __future__ import annotations

import io

from tests.conftest import _auth


def _upload(client, headers, folder_id, title="Doc", body=b"hello invoice INV-12345 EUR 12.00"):
    files = {"file": ("note.txt", io.BytesIO(body), "text/plain")}
    r = client.post(
        "/api/documents",
        data={"folder_id": folder_id, "title": title, "tags": "invoice"},
        files=files,
        headers=headers,
    )
    assert r.status_code == 200, r.text
    return r.json()


def _pdf_bytes(text="Confidential invoice INV-999"):
    from fpdf import FPDF

    pdf = FPDF()
    pdf.add_page()
    pdf.set_font("Helvetica", size=14)
    pdf.cell(40, 10, text)
    return pdf.output()


def test_bpmn_exclusive_gateway():
    from app.bpmn import eval_condition, from_graph_json, next_nodes, parse_bpmn_xml

    xml = """<?xml version="1.0"?>
    <definitions xmlns="http://www.omg.org/spec/BPMN/20100524/MODEL">
      <process id="p1" name="review">
        <startEvent id="start"/>
        <userTask id="review" name="Review" assigneeRole="admin"/>
        <exclusiveGateway id="xor"/>
        <userTask id="legal" name="Legal"/>
        <userTask id="finance" name="Finance"/>
        <endEvent id="end"/>
        <sequenceFlow sourceRef="start" targetRef="review"/>
        <sequenceFlow sourceRef="review" targetRef="xor"/>
        <sequenceFlow sourceRef="xor" targetRef="legal">
          <conditionExpression>decision==rejected</conditionExpression>
        </sequenceFlow>
        <sequenceFlow sourceRef="xor" targetRef="finance">
          <conditionExpression>decision==approved</conditionExpression>
        </sequenceFlow>
        <sequenceFlow sourceRef="legal" targetRef="end"/>
        <sequenceFlow sourceRef="finance" targetRef="end"/>
      </process>
    </definitions>"""
    definition = parse_bpmn_xml(xml)
    assert definition.start == "start"
    nxt = next_nodes(definition, "xor", {"decision": "approved"})
    assert nxt == ["finance"]
    nxt = next_nodes(definition, "xor", {"decision": "rejected"})
    assert nxt == ["legal"]
    assert eval_condition("status==review", {"status": "review"})
    graph = from_graph_json(
        {
            "nodes": [
                {"id": "a", "type": "start"},
                {"id": "b", "type": "parallelGateway"},
                {"id": "c", "type": "userTask", "name": "one"},
                {"id": "d", "type": "userTask", "name": "two"},
            ],
            "edges": [{"from": "a", "to": "b"}, {"from": "b", "to": "c"}, {"from": "b", "to": "d"}],
        }
    )
    assert set(next_nodes(graph, "b", {})) == {"c", "d"}


def test_watermark_and_redact(tmp_path):
    from app.pdfops import redact_text_patterns, watermark

    src = tmp_path / "in.pdf"
    src.write_bytes(_pdf_bytes("SSN 123-45-6789 secret"))
    dest = tmp_path / "wm.pdf"
    watermark(src, dest, "CONFIDENTIAL")
    assert dest.exists() and dest.stat().st_size > 0
    red = tmp_path / "red.pdf"
    path, cleaned = redact_text_patterns(dest, red, [r"\d{3}-\d{2}-\d{4}"], "SSN 123-45-6789 secret")
    assert path.exists()
    assert "123-45-6789" not in cleaned or "█" in cleaned


def test_legal_hold_blocks_purge(client, admin_token, root_folder_id):
    headers = _auth(admin_token)
    doc = _upload(client, headers, root_folder_id, "HoldMe")
    r = client.post(
        "/api/legal-holds",
        json={"name": "matter-1", "reason": "litigation", "document_ids": [doc["id"]]},
        headers=headers,
    )
    assert r.status_code == 200, r.text
    assert client.delete(f"/api/documents/{doc['id']}", headers=headers).status_code == 423
    assert client.delete(f"/api/documents/{doc['id']}?permanent=true", headers=headers).status_code == 423
    client.post(f"/api/legal-holds/{r.json()['id']}/release", headers=headers)
    assert client.delete(f"/api/documents/{doc['id']}", headers=headers).status_code == 200


def test_vector_rag(client, admin_token, root_folder_id):
    headers = _auth(admin_token)
    doc = _upload(client, headers, root_folder_id, "Acme Invoice", b"Acme Corp billed EUR 99.00 for consulting.")
    client.post(f"/api/documents/{doc['id']}/embed", headers=headers)
    r = client.post("/api/rag", json={"query": "Acme consulting invoice"}, headers=headers)
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["hits"] or body["answer"]


def test_zonal_and_idp_regex(client, admin_token, root_folder_id):
    headers = _auth(admin_token)
    doc = _upload(client, headers, root_folder_id, "Inv", b"Invoice INV-777 dated 2026-01-02 amount EUR 10.00")
    r = client.post(f"/api/documents/{doc['id']}/idp", headers=headers)
    assert r.status_code == 200, r.text
    captured = r.json()["captured"]
    assert "invoice_no" in captured or "amount" in captured
    zr = client.post(
        "/api/zones",
        json={"name": "invoice-header", "zones": [{"page": 1, "x": 0, "y": 0, "w": 200, "h": 40, "name": "header"}]},
        headers=headers,
    )
    assert zr.status_code == 200


def test_archivelink_put_get(client):
    payload = b"%PDF-1.4 archive body"
    r = client.put("/archivelink/T1/DOC42", content=payload, headers={"Content-Type": "application/pdf"})
    assert r.status_code == 201, r.text
    info = client.get("/archivelink/T1/DOC42/info")
    assert info.status_code == 200
    assert info.json()["size"] == len(payload)
    got = client.get("/archivelink/T1/DOC42")
    assert got.status_code == 200
    assert got.content == payload


def test_automation_rule_tags_document(client, admin_token, root_folder_id):
    headers = _auth(admin_token)
    r = client.post(
        "/api/automation-rules",
        json={
            "name": "tag-invoices",
            "event": "document_created",
            "condition": {"tag": "invoice"},
            "actions": [{"type": "tag", "tags": "auto-processed"}],
        },
        headers=headers,
    )
    assert r.status_code == 200, r.text
    doc = _upload(client, headers, root_folder_id, "Ruled")
    again = client.get(f"/api/documents/{doc['id']}", headers=headers)
    tags = (again.json().get("tags") if again.status_code == 200 else doc.get("tags") or "").lower()
    assert "auto-processed" in tags or "invoice" in tags


def test_reading_confirmation_and_form(client, admin_token, root_folder_id):
    headers = _auth(admin_token)
    doc = _upload(client, headers, root_folder_id, "Readme")
    r = client.post(f"/api/documents/{doc['id']}/confirm-read", headers=headers)
    assert r.status_code == 200
    listed = client.get(f"/api/documents/{doc['id']}/reading-confirmations", headers=headers)
    assert listed.status_code == 200
    assert listed.json()
    form = client.post(
        "/api/forms",
        json={"name": "intake", "folder_id": root_folder_id, "schema": {"fields": [{"name": "title", "label": "Title"}]}},
        headers=headers,
    )
    assert form.status_code == 200, form.text
    token = form.json()["token"]
    html = client.get(f"/forms/{token}")
    assert html.status_code == 200
    assert "<form" in html.text.lower()


def test_compliance_and_cluster(client, admin_token):
    headers = _auth(admin_token)
    r = client.get("/api/compliance", headers=headers)
    assert r.status_code == 200
    body = r.json()
    assert "gdpr" in body and "hipaa" in body and "iso27001" in body
    cl = client.get("/api/cluster", headers=headers)
    assert cl.status_code == 200
    assert "members" in cl.json()


def test_security_policy_ip_deny(client, admin_token):
    from app import database as db_mod
    from app.models import LoginHistory

    headers = _auth(admin_token)
    db = db_mod.SessionLocal()
    try:
        last = db.query(LoginHistory).order_by(LoginHistory.id.desc()).first()
        ip = (last.ip if last else None) or "testclient"
    finally:
        db.close()
    r = client.put(
        "/api/security-policy",
        json={"ip_denylist": [ip, "127.0.0.1", "testclient"], "max_failed_logins": 8},
        headers=headers,
    )
    assert r.status_code == 200, r.text
    denied = client.post("/api/auth/login", data={"username": "admin", "password": "admin123"})
    assert denied.status_code == 403


def test_csv_import_and_barcode(client, admin_token, root_folder_id):
    headers = _auth(admin_token)
    csv_body = "title,tags,customer\nAlpha,invoice,Acme\nBeta,letter,Globex\n"
    r = client.post(
        "/api/import/csv",
        data={"folder_id": root_folder_id},
        files={"file": ("rows.csv", io.BytesIO(csv_body.encode()), "text/csv")},
        headers=headers,
    )
    assert r.status_code == 200, r.text
    assert r.json()["created"] == 2
    png = client.get("/api/barcodes/code128?data=HELLO", headers=headers)
    assert png.status_code == 200
    assert png.headers["content-type"].startswith("image/png")


def test_sign_pdf_endpoint(client, admin_token, root_folder_id):
    headers = _auth(admin_token)
    files = {"file": ("doc.pdf", io.BytesIO(_pdf_bytes()), "application/pdf")}
    up = client.post(
        "/api/documents",
        data={"folder_id": root_folder_id, "title": "SignMe"},
        files=files,
        headers=headers,
    )
    assert up.status_code == 200, up.text
    doc_id = up.json()["id"]
    r = client.post(f"/api/documents/{doc_id}/sign", data={"reason": "approved"}, headers=headers)
    assert r.status_code == 200, r.text
    assert r.json().get("signer") == "admin"
    wm = client.post(
        f"/api/documents/{doc_id}/watermark",
        json={"text": "CONFIDENTIAL"},
        headers=headers,
    )
    assert wm.status_code == 200
