"""Tests for online users presence tracking and the enterprise audit trail system."""

import pytest
from fastapi.testclient import TestClient

from app.audit import audit, calculate_audit_checksum
from app.database import Base, get_db
from app.models import AuditLog, User
from app.presence import presence_manager


def test_presence_manager_basic():
    presence_manager.touch(
        user_id=999,
        username="alice",
        role="admin",
        email="alice@example.com",
        ip="192.168.1.100",
        user_agent="Mozilla/5.0 Test",
        current_path="/folders",
    )
    online = presence_manager.get_online(max_idle_seconds=60)
    assert any(u["username"] == "alice" for u in online)
    assert presence_manager.count_online(max_idle_seconds=60) >= 1

    presence_manager.remove(999)
    online_after = presence_manager.get_online(max_idle_seconds=60)
    assert not any(u["user_id"] == 999 for u in online_after)


def test_presence_api_endpoints(client: TestClient, admin_user: User, admin_token: str):
    headers = {"Authorization": f"Bearer {admin_token}"}
    # Heartbeat
    resp = client.post(
        "/api/users/heartbeat",
        json={"current_path": "/dashboard", "active_tab": "dashboard"},
        headers=headers,
    )
    assert resp.status_code == 200
    data = resp.json()
    assert data.get("ok") is True
    assert data.get("online_count", 0) >= 1

    # Online users list
    resp = client.get("/api/users/online", headers=headers)
    assert resp.status_code == 200
    users = resp.json()
    assert isinstance(users, list)
    assert any(u["username"] == admin_user.username for u in users)

    # Online count
    resp = client.get("/api/users/online/count", headers=headers)
    assert resp.status_code == 200
    assert resp.json().get("count", 0) >= 1


def test_audit_checksum_and_creation(db_session, admin_user: User):
    log = audit(
        db=db_session,
        user=admin_user,
        action="TEST_ACTION",
        resource_type="document",
        resource_id=42,
        resource_name="Contract_Q3.pdf",
        details="Tested enterprise audit log creation",
        severity="HIGH",
        status="SUCCESS",
        details_json={"custom_field": "val123"},
        ip="10.0.0.5",
        user_agent="AutomatedTestClient/1.0",
    )

    assert log.id is not None
    assert log.username == admin_user.username
    assert log.actor_role == admin_user.role
    assert log.severity == "HIGH"
    assert log.status == "SUCCESS"
    assert log.resource_name == "Contract_Q3.pdf"
    assert log.checksum is not None
    assert len(log.checksum) == 64  # SHA-256 hex string


def test_audit_api_filtering_and_stats(client: TestClient, admin_user: User, admin_token: str, db_session):
    headers = {"Authorization": f"Bearer {admin_token}"}
    # Insert multiple test audit logs
    audit(
        db=db_session,
        user=admin_user,
        action="CRITICAL_SECURITY_EVENT",
        resource_type="auth",
        details="Suspicious login pattern detected",
        severity="CRITICAL",
        status="SUSPICIOUS",
        ip="198.51.100.22",
    )
    audit(
        db=db_session,
        user=admin_user,
        action="DOCUMENT_VIEW",
        resource_type="document",
        resource_id=10,
        resource_name="AnnualReport.pdf",
        details="Viewed AnnualReport.pdf",
        severity="INFO",
        status="SUCCESS",
        ip="10.0.0.1",
    )

    # List audit with filtering
    res_all = client.get("/api/audit?limit=100", headers=headers)
    assert res_all.status_code == 200
    records = res_all.json()
    assert len(records) >= 2

    # Filter by severity
    res_crit = client.get("/api/audit?severity=CRITICAL", headers=headers)
    assert res_crit.status_code == 200
    crit_records = res_crit.json()
    assert all(r["severity"] == "CRITICAL" for r in crit_records)

    # Search filter
    res_search = client.get("/api/audit?search=Suspicious", headers=headers)
    assert res_search.status_code == 200
    search_records = res_search.json()
    assert any("Suspicious" in r["details"] for r in search_records)

    # Stats endpoint
    res_stats = client.get("/api/audit/stats", headers=headers)
    assert res_stats.status_code == 200
    stats = res_stats.json()
    assert stats["total_events"] >= 2
    assert "CRITICAL" in stats["by_severity"]
    assert stats["security_alerts"] >= 1


def test_audit_export_endpoints(client: TestClient, admin_user: User, admin_token: str):
    headers = {"Authorization": f"Bearer {admin_token}"}
    # CSV export
    res_csv = client.get("/api/audit/export?format=csv", headers=headers)
    assert res_csv.status_code == 200
    assert "text/csv" in res_csv.headers["content-type"]
    assert "SHA256 Checksum" in res_csv.text

    # JSON export
    res_json = client.get("/api/audit/export?format=json", headers=headers)
    assert res_json.status_code == 200
    assert "application/json" in res_json.headers["content-type"]
    data = res_json.json()
    assert "records" in data
    assert len(data["records"]) >= 1


def test_client_security_event_logging(client: TestClient, admin_user: User, admin_token: str):
    headers = {"Authorization": f"Bearer {admin_token}"}
    payload = {
        "event_type": "SUSPICIOUS_CLIPBOARD_COPY",
        "details": "Mass data copy attempted on confidential document view",
        "resource_type": "document",
        "resource_id": 99,
        "severity": "HIGH",
    }
    resp = client.post("/api/audit/client-event", json=payload, headers=headers)
    assert resp.status_code == 200
    assert resp.json().get("ok") is True
    assert resp.json().get("audit_id") is not None
