"""Power search, catalogs, conversion, nested extract, classifier, shares."""
from __future__ import annotations

import zipfile
from io import BytesIO
from pathlib import Path

from app.classifier import predict, train
from app.convert import merge_pdfs, to_pdf
from app.extract import extract_nested
from app.miniquery import match, parse_date_expr
from app.querylang import apply_filters, parse_query


def _auth(token: str) -> dict:
    return {"Authorization": f"Bearer {token}"}


def _upload(client, token, folder_id, name="note.txt", body=b"hello", **data):
    payload = {"folder_id": str(folder_id), "title": name, **data}
    return client.post(
        "/api/documents",
        headers=_auth(token),
        data=payload,
        files={"file": (name, body, "text/plain")},
    )


def test_power_search_boolean_and_fields():
    p = parse_query('tag:invoice AND NOT tag:paid corr.org:Acme dateIn:today;-7d,today')
    assert p.tree is not None
    assert p.tree.kind in ("and", "or")
    p2 = parse_query('tag:invoice OR tag:receipt')
    assert p2.tree.kind == "or"
    p3 = parse_query('tag:invoice correspondent:acme due:overdue "purchase order"')
    assert "invoice" in p3.filters["tags"]
    assert p3.filters["correspondent"] == "acme"
    assert "purchase order" in p3.fulltext


def test_date_arithmetic():
    d = parse_date_expr("today;-7d")
    assert d is not None
    n = parse_date_expr("now")
    assert n is not None
    assert (n - d).days >= 6


def test_miniquery_and_or(client, admin_token, root_folder_id):
    from app import database as db_mod
    from app.models import Document

    up = _upload(client, admin_token, root_folder_id, tags="invoice").json()
    db = db_mod.SessionLocal()
    try:
        doc = db.get(Document, up["id"])
        assert match(db, doc, {"tag": "invoice"})
        assert match(db, doc, {"and": [{"tag": "invoice"}, {"not": {"tag": "paid"}}]})
        assert not match(db, doc, {"tag": "paid"})
    finally:
        db.close()


def test_organizations_and_equipment(client, admin_token):
    headers = _auth(admin_token)
    org = client.post("/api/organizations", headers=headers, data={"name": "Acme Ltd", "emails": "billing@acme.test"})
    assert org.status_code == 200, org.text
    eq = client.post("/api/equipment", headers=headers, data={"name": "Scanner-1"})
    assert eq.status_code == 200
    listed = client.get("/api/organizations", headers=headers).json()
    assert any(o["name"] == "Acme Ltd" for o in listed)


def test_confirm_and_next(client, admin_token, root_folder_id):
    headers = _auth(admin_token)
    doc = _upload(client, admin_token, root_folder_id).json()
    got = client.get(f"/api/documents/{doc['id']}", headers=headers).json()
    assert got["confirmed"] is False
    r = client.post(f"/api/documents/{doc['id']}/confirm", headers=headers)
    assert r.status_code == 200
    got = client.get(f"/api/documents/{doc['id']}", headers=headers).json()
    assert got["confirmed"] is True
    client.post(f"/api/documents/{doc['id']}/unconfirm", headers=headers)
    nxt = client.get("/api/documents/next?q=confirmed:new", headers=headers)
    assert nxt.status_code == 200
    assert nxt.json()["id"] == doc["id"]


def test_group_upload_and_skip_dup(client, admin_token, root_folder_id):
    headers = _auth(admin_token)
    files = [
        ("files", ("a.txt", b"alpha-file", "text/plain")),
        ("files", ("b.txt", b"beta-file", "text/plain")),
    ]
    r = client.post(
        "/api/documents/group",
        headers=headers,
        data={"folder_id": str(root_folder_id), "title": "bundle"},
        files=files,
    )
    assert r.status_code == 200, r.text
    atts = client.get(f"/api/documents/{r.json()['id']}/attachments", headers=headers).json()
    assert any(a["name"] == "b.txt" for a in atts)
    body = b"unique-skip-dup-payload"
    a = _upload(client, admin_token, root_folder_id, name="x.txt", body=body, skip_duplicates="true")
    assert a.status_code == 200
    b = _upload(client, admin_token, root_folder_id, name="y.txt", body=body, skip_duplicates="true")
    assert b.status_code == 409


def test_nested_zip_extract(tmp_path):
    inner = BytesIO()
    with zipfile.ZipFile(inner, "w") as zf:
        zf.writestr("deep/hello.txt", "nested hello")
    outer = tmp_path / "outer.zip"
    with zipfile.ZipFile(outer, "w") as zf:
        zf.writestr("inner.zip", inner.getvalue())
    text, files = extract_nested(outer, tmp_path / "out")
    names = [f.name for f in files]
    assert "inner.zip" in names or any(p.name == "hello.txt" for p in files)
    assert any(p.name == "hello.txt" for p in files)


def test_text_to_pdf_and_merge(tmp_path):
    src = tmp_path / "note.txt"
    src.write_text("Invoice 42", encoding="utf-8")
    pdf = tmp_path / "note.pdf"
    to_pdf(src, pdf)
    assert pdf.exists() and pdf.stat().st_size > 0
    out = tmp_path / "merged.pdf"
    merge_pdfs([pdf, pdf], out)
    assert out.exists() and out.stat().st_size > 0


def test_encrypted_pdf(tmp_path):
    from pypdf import PdfReader, PdfWriter

    plain = tmp_path / "plain.pdf"
    src = tmp_path / "t.txt"
    src.write_text("secret page", encoding="utf-8")
    to_pdf(src, plain)
    writer = PdfWriter()
    reader = PdfReader(str(plain))
    for page in reader.pages:
        writer.add_page(page)
    writer.encrypt("pw")
    enc = tmp_path / "enc.pdf"
    with enc.open("wb") as fh:
        writer.write(fh)
    dest = tmp_path / "out.pdf"
    to_pdf(enc, dest, password="pw")
    assert dest.exists()


def test_classifier_train_predict(client, admin_token, root_folder_id):
    from app import database as db_mod

    _upload(client, admin_token, root_folder_id, name="inv.txt", body=b"this is an invoice for services", tags="invoice")
    db = db_mod.SessionLocal()
    try:
        stats = train(db, whitelist=["finance"], blacklist=[])
        assert "docs" in stats
        pred = predict("invoice for services rendered")
        assert isinstance(pred, list)
    finally:
        db.close()


def test_query_share_and_open_alias(client, admin_token, root_folder_id):
    headers = _auth(admin_token)
    _upload(client, admin_token, root_folder_id, tags="invoice")
    created = client.post(
        "/api/query-shares",
        headers=headers,
        json={"name": "invoices", "query": "tag:invoice"},
    )
    assert created.status_code == 200, created.text
    token = created.json()["token"]
    page = client.get(f"/s/{token}")
    assert page.status_code == 200
    assert b"invoice" in page.content.lower() or b"NewtonEDMS" in page.content

    src = client.post(
        "/api/open-uploads",
        headers=headers,
        json={"name": "phone", "folder_id": root_folder_id, "skip_duplicates": True},
    )
    assert src.status_code == 200
    ot = src.json()["token"]
    up = client.post(
        f"/api/v1/open/upload/item/{ot}",
        files={"file": ("from-phone.txt", b"hello from phone", "text/plain")},
    )
    assert up.status_code == 200, up.text


def test_collectives_and_ui_settings(client, admin_token):
    headers = _auth(admin_token)
    cur = client.get("/api/collectives/current", headers=headers)
    assert cur.status_code == 200
    assert cur.json()["name"]
    ui = client.put("/api/ui-settings", headers=headers, json={"powerSearch": True, "cardLayout": "cards", "tagCount": 5})
    assert ui.status_code == 200
    cat = client.get("/api/i18n/de")
    assert cat.status_code == 200
    assert "nav.documents" in cat.json()


def test_or_query_finds_either_tag(client, admin_token, root_folder_id):
    headers = _auth(admin_token)
    a = _upload(client, admin_token, root_folder_id, name="a.txt", body=b"a", tags="invoice").json()
    b = _upload(client, admin_token, root_folder_id, name="b.txt", body=b"b", tags="receipt").json()
    found = client.get("/api/query?q=tag:invoice OR tag:receipt", headers=headers)
    assert found.status_code == 200
    ids = {d["id"] for d in found.json()}
    assert a["id"] in ids and b["id"] in ids
