"""Comprehensive tests for ProcessMaker Enterprise Workflow Engine inside NewtonEDMS."""
import pytest
from datetime import timedelta
from fastapi.testclient import TestClient

from app.database import now
from app.models import Document, Folder, Task, User, WorkflowInstance, WorkflowTemplate, WorkflowTransitionLog
from app.workflow_engine import advance_task, check_and_escalate_slas, start_workflow


@pytest.fixture
def auth_client(client, admin_token):
    client.headers.update({"Authorization": f"Bearer {admin_token}"})
    return client


@pytest.fixture
def manager_user(db_session):
    u = db_session.query(User).filter(User.username == "test_mgr").first()
    if not u:
        u = User(username="test_mgr", email="mgr@example.com", hashed_password="x", role="manager", is_active=True)
        db_session.add(u)
        db_session.commit()
        db_session.refresh(u)
    return u


@pytest.fixture
def legal_user(db_session):
    u = db_session.query(User).filter(User.username == "test_legal").first()
    if not u:
        u = User(username="test_legal", email="legal@example.com", hashed_password="x", role="legal", is_active=True)
        db_session.add(u)
        db_session.commit()
        db_session.refresh(u)
    return u


def test_conditional_auto_approval_under_threshold(db_session, admin_user, root_folder_id):
    # 1. Document with Amount = 500
    doc = Document(
        name="PO-500.pdf",
        title="PO-500.pdf",
        file_path="/storage/po500.pdf",
        folder_id=root_folder_id,
        created_by=admin_user.id,
        status="draft",
        metadata_json={"amount": 500, "vendor": "Acme Tools"},
    )
    db_session.add(doc)
    db_session.commit()
    db_session.refresh(doc)

    # 2. Template with auto_approval_rule: "amount < 1000"
    tpl = WorkflowTemplate(
        name="PO Approval Workflow",
        routing_type="sequential",
        auto_approval_rule="amount < 1000",
        steps=[{"name": "Manager Approval", "assignee_role": "manager"}],
        created_by=admin_user.id,
    )
    db_session.add(tpl)
    db_session.commit()
    db_session.refresh(tpl)

    # 3. Start Workflow -> Should auto-approve immediately
    inst = start_workflow(db_session, tpl.id, doc.id, admin_user.id)
    assert inst.status == "completed"
    assert doc.status == "approved"

    # Verify Timeline Log
    logs = db_session.query(WorkflowTransitionLog).filter(WorkflowTransitionLog.instance_id == inst.id).all()
    assert len(logs) == 1
    assert logs[0].action == "AUTO_APPROVE"
    assert "amount < 1000" in logs[0].comment


def test_sequential_routing_and_dynamic_form_capture(db_session, admin_user, manager_user, root_folder_id):
    # Document with Amount = 1500 (Exceeds auto-approval)
    doc = Document(
        name="PO-1500.pdf",
        title="PO-1500.pdf",
        file_path="/storage/po1500.pdf",
        folder_id=root_folder_id,
        created_by=admin_user.id,
        status="draft",
        metadata_json={"amount": 1500, "vendor": "Globex Corp"},
    )
    db_session.add(doc)
    db_session.commit()
    db_session.refresh(doc)

    tpl = WorkflowTemplate(
        name="Purchase Order Multi-Step",
        routing_type="sequential",
        auto_approval_rule="amount < 1000",
        steps=[
            {"name": "Manager Review", "assignee_role": "manager", "form_schema": [{"name": "po_tax_id", "label": "Tax ID"}]},
            {"name": "Finance Approval", "assignee_role": "admin", "form_schema": [{"name": "cost_center", "label": "Cost Center"}]},
        ],
        created_by=admin_user.id,
    )
    db_session.add(tpl)
    db_session.commit()
    db_session.refresh(tpl)

    # Start -> Enters 'under_review' and spawns step 0
    inst = start_workflow(db_session, tpl.id, doc.id, admin_user.id)
    assert inst.status == "running"
    assert doc.status == "under_review"

    # Verify Task 0 for Manager
    tasks = db_session.query(Task).filter(Task.instance_id == inst.id, Task.status == "pending").all()
    assert len(tasks) == 1
    assert tasks[0].step_name == "Manager Review"

    # Manager approves and inputs dynamic form data + signature
    res1 = advance_task(
        db_session,
        tasks[0].id,
        action="approve",
        user_id=manager_user.id,
        comment="Looks good, budget verified",
        form_data={"po_tax_id": "TAX-99882"},
        signature="SIG-MGR-001",
    )
    assert res1["status"] == "advanced"
    assert doc.status == "under_review"

    # Step 1 should now be spawned for Admin
    tasks2 = db_session.query(Task).filter(Task.instance_id == inst.id, Task.status == "pending").all()
    assert len(tasks2) == 1
    assert tasks2[0].step_name == "Finance Approval"

    # Admin approves Step 1
    res2 = advance_task(
        db_session,
        tasks2[0].id,
        action="approve",
        user_id=admin_user.id,
        comment="Final finance approval given",
        form_data={"cost_center": "CC-102"},
        signature="SIG-ADM-002",
    )
    assert res2["status"] == "advanced"
    assert inst.status == "completed"
    assert doc.status == "approved"

    # Check Timeline / Audit Trail
    logs = db_session.query(WorkflowTransitionLog).filter(WorkflowTransitionLog.instance_id == inst.id).all()
    assert len(logs) >= 3  # SUBMIT, Step 0 APPROVE, Step 1 APPROVE
    actions = [l.action for l in logs]
    assert "SUBMIT" in actions
    assert "APPROVE" in actions


def test_parallel_all_routing(db_session, admin_user, manager_user, legal_user, root_folder_id):
    # Parallel approval where both manager and legal must sign off
    doc = Document(
        name="HighValueContract.docx",
        title="HighValueContract.docx",
        file_path="/storage/contract.docx",
        folder_id=root_folder_id,
        created_by=admin_user.id,
        status="draft",
        metadata_json={"amount": 75000},
    )
    db_session.add(doc)
    db_session.commit()
    db_session.refresh(doc)

    tpl = WorkflowTemplate(
        name="Parallel Contract Review",
        routing_type="parallel_all",
        steps=[
            {"name": "Joint Review", "assignee_ids": [manager_user.id, legal_user.id]},
        ],
        created_by=admin_user.id,
    )
    db_session.add(tpl)
    db_session.commit()
    db_session.refresh(tpl)

    inst = start_workflow(db_session, tpl.id, doc.id, admin_user.id)
    pending_tasks = db_session.query(Task).filter(Task.instance_id == inst.id, Task.status == "pending").all()
    assert len(pending_tasks) == 2  # Manager + Legal tasks created concurrently

    # Manager signs off first
    t_mgr = [t for t in pending_tasks if t.assignee_id == manager_user.id][0]
    res_mgr = advance_task(db_session, t_mgr.id, action="approve", user_id=manager_user.id, comment="Manager approved")
    assert res_mgr["status"] == "waiting_for_peers"
    assert inst.status == "running"
    assert doc.status == "under_review"

    # Legal signs off second -> completes workflow
    t_legal = [t for t in pending_tasks if t.assignee_id == legal_user.id][0]
    res_legal = advance_task(db_session, t_legal.id, action="approve", user_id=legal_user.id, comment="Legal approved")
    assert res_legal["status"] == "advanced"
    assert inst.status == "completed"
    assert doc.status == "approved"


def test_sla_enforcement_and_auto_escalation(db_session, admin_user, manager_user, root_folder_id):
    doc = Document(
        name="UrgentDoc.pdf",
        title="UrgentDoc.pdf",
        file_path="/storage/urgent.pdf",
        folder_id=root_folder_id,
        created_by=admin_user.id,
        status="draft",
    )
    db_session.add(doc)
    db_session.commit()
    db_session.refresh(doc)

    tpl = WorkflowTemplate(
        name="Urgent SLA Workflow",
        routing_type="sequential",
        sla_hours=2,
        escalate_to_role="admin",
        steps=[{"name": "Immediate Review", "assignee_id": manager_user.id, "due_days": 0}],
        created_by=admin_user.id,
    )
    db_session.add(tpl)
    db_session.commit()
    db_session.refresh(tpl)

    inst = start_workflow(db_session, tpl.id, doc.id, admin_user.id)
    task = db_session.query(Task).filter(Task.instance_id == inst.id).first()
    
    # Manually backdate task.due_at to simulate SLA expiration
    task.due_at = now() - timedelta(hours=5)
    db_session.commit()

    # Trigger SLA check & auto-escalation
    escalated = check_and_escalate_slas(db_session)
    assert len(escalated) >= 1
    
    db_session.refresh(task)
    assert task.escalated is True
    assert task.escalated_to_id == admin_user.id
    
    # Check SLA breach log in timeline
    logs = db_session.query(WorkflowTransitionLog).filter(
        WorkflowTransitionLog.instance_id == inst.id,
        WorkflowTransitionLog.action == "ESCALATE",
    ).all()
    assert len(logs) == 1
    assert "SLA Breached" in logs[0].comment
