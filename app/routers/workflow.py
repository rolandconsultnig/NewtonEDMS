"""Workflow, tasks, BPMN engine and ProcessMaker approval routes."""
from __future__ import annotations

from datetime import timedelta

from fastapi import APIRouter, Body, Depends, HTTPException
from sqlalchemy.orm import Session

from app.audit import audit
from app.database import get_db, now
from app.models import (
    Document,
    Folder,
    Notification,
    Task,
    User,
    WorkflowInstance,
    WorkflowTemplate,
    WorkflowTransitionLog,
)
from app.permissions import has_permission
from app.schemas import (
    NotificationOut,
    TaskAction,
    TaskCreate,
    TaskOut,
    WorkflowInstanceOut,
    WorkflowStep,
    WorkflowTemplateCreate,
    WorkflowTemplateOut,
    WorkflowTransitionLogOut,
)
from app.security import get_current_user, require_role
from app.workflow_engine import advance_task, check_and_escalate_slas, start_workflow as start_workflow_engine

router = APIRouter(prefix="/api", tags=["workflow"])

VALID_ROLES = {"superadmin", "admin", "manager", "user", "compliance", "finance", "legal", "executive"}


def _validated_steps(raw_steps) -> list[WorkflowStep]:
    """Validate template steps against the WorkflowStep schema."""
    steps = [WorkflowStep.model_validate(s) for s in (raw_steps or [])]
    for step in steps:
        if not step.name or not step.name.strip():
            raise HTTPException(status_code=400, detail="Every workflow step needs a name")
        if not step.assignee_id and not step.assignee_role:
            raise HTTPException(status_code=400, detail="Every workflow step needs an assignee_id or assignee_role")
    return steps


def start_workflow_internal(db: Session, doc_id: int, template_id: int, created_by: int) -> WorkflowInstance:
    """Start a workflow without HTTP; used by folder triggers and automation rules."""
    d = db.get(Document, doc_id)
    w = db.get(WorkflowTemplate, template_id)
    if not d or not w:
        raise ValueError("document or template missing")
    if (
        db.query(WorkflowInstance)
        .filter(WorkflowInstance.document_id == doc_id, WorkflowInstance.status == "running")
        .first()
    ):
        raise ValueError("A workflow is already running on this document")
    return start_workflow_engine(db, template_id, doc_id, created_by)


@router.get("/workflows", response_model=list[WorkflowTemplateOut])
def list_workflows(
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    return db.query(WorkflowTemplate).order_by(WorkflowTemplate.name).all()


@router.get("/workflows/queue", response_model=list[TaskOut])
def get_workflow_queue(
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    """Fetch all pending tasks in the current user's approval queue (direct or role-assigned)."""
    q = (
        db.query(Task, WorkflowInstance.document_id, User.username)
        .join(WorkflowInstance, Task.instance_id == WorkflowInstance.id)
        .outerjoin(User, Task.assignee_id == User.id)
        .filter(Task.status == "pending")
    )
    if user.role not in ("superadmin", "admin"):
        q = q.filter((Task.assignee_id == user.id) | (Task.assignee_role == user.role))
    
    results = []
    for t, doc_id, username in q.order_by(Task.due_at.asc().nullslast(), Task.created_at.asc()).all():
        results.append(_format_task_out(t, doc_id, username))
    return results


@router.get("/workflows/{workflow_id}", response_model=WorkflowTemplateOut)
def get_workflow(
    workflow_id: int,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    w = db.get(WorkflowTemplate, workflow_id)
    if not w:
        raise HTTPException(status_code=404, detail="Workflow not found")
    return w


@router.post("/workflows", response_model=WorkflowTemplateOut)
def create_workflow(
    payload: WorkflowTemplateCreate,
    db: Session = Depends(get_db),
    user: User = Depends(require_role("superadmin", "admin", "manager")),
):
    steps = _validated_steps(payload.steps)
    w = WorkflowTemplate(
        name=payload.name,
        description=payload.description,
        routing_type=payload.routing_type or "sequential",
        steps=[s.model_dump() for s in steps],
        graph=payload.graph or {},
        form_schema=payload.form_schema or [],
        sla_hours=payload.sla_hours or 24,
        escalate_to_role=payload.escalate_to_role or "manager",
        auto_approval_rule=payload.auto_approval_rule,
        created_by=user.id,
        created_at=now(),
    )
    db.add(w)
    db.commit()
    db.refresh(w)
    audit(db, user, "WORKFLOW_CREATE", "workflow_template", w.id, w.name)
    return w


@router.put("/workflows/{workflow_id}", response_model=WorkflowTemplateOut)
def update_workflow(
    workflow_id: int,
    payload: WorkflowTemplateCreate,
    db: Session = Depends(get_db),
    user: User = Depends(require_role("superadmin", "admin", "manager")),
):
    w = db.get(WorkflowTemplate, workflow_id)
    if not w:
        raise HTTPException(status_code=404, detail="Workflow not found")
    steps = _validated_steps(payload.steps)
    w.name = payload.name
    w.description = payload.description
    w.routing_type = payload.routing_type or w.routing_type or "sequential"
    w.steps = [s.model_dump() for s in steps]
    if payload.graph:
        w.graph = payload.graph
    if payload.form_schema is not None:
        w.form_schema = payload.form_schema
    if payload.sla_hours:
        w.sla_hours = payload.sla_hours
    if payload.escalate_to_role:
        w.escalate_to_role = payload.escalate_to_role
    if payload.auto_approval_rule is not None:
        w.auto_approval_rule = payload.auto_approval_rule
    db.commit()
    db.refresh(w)
    audit(db, user, "WORKFLOW_UPDATE", "workflow_template", w.id, w.name)
    return w


@router.delete("/workflows/{workflow_id}")
def delete_workflow(
    workflow_id: int,
    db: Session = Depends(get_db),
    user: User = Depends(require_role("superadmin", "admin")),
):
    w = db.get(WorkflowTemplate, workflow_id)
    if not w:
        raise HTTPException(status_code=404, detail="Workflow not found")
    if db.query(WorkflowInstance).filter(WorkflowInstance.template_id == workflow_id).first():
        raise HTTPException(
            status_code=409, detail="Workflow has active or historical instances; cannot delete"
        )
    db.delete(w)
    db.commit()
    audit(db, user, "WORKFLOW_DELETE", "workflow_template", workflow_id, w.name)
    return {"ok": True}


@router.post("/documents/{doc_id}/workflows", response_model=WorkflowInstanceOut)
def start_document_workflow(
    doc_id: int,
    template_id: int,
    variables: dict | None = Body(default=None),
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    d = db.get(Document, doc_id)
    if not d:
        raise HTTPException(status_code=404, detail="Document not found")
    f = db.get(Folder, d.folder_id)
    if not has_permission(db, user, "write", f, d):
        raise HTTPException(status_code=403, detail="No permission to start workflow on this document")
    w = db.get(WorkflowTemplate, template_id)
    if not w:
        raise HTTPException(status_code=404, detail="Workflow template not found")
    
    # Check running instance
    if db.query(WorkflowInstance).filter(WorkflowInstance.document_id == doc_id, WorkflowInstance.status == "running").first():
        raise HTTPException(status_code=409, detail="A workflow is already running on this document")

    try:
        inst = start_workflow_engine(db, template_id, doc_id, user.id, variables)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    audit(db, user, "WORKFLOW_START", "workflow_instance", inst.id, f"Template {w.id} on document {doc_id}")
    return inst


@router.get("/workflow-instances", response_model=list[WorkflowInstanceOut])
def list_instances(
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    q = db.query(WorkflowInstance)
    if user.role not in ("superadmin", "admin", "manager"):
        q = q.filter(WorkflowInstance.created_by == user.id)
    return q.order_by(WorkflowInstance.created_at.desc()).all()


@router.get("/workflows/instances/{instance_id}/timeline", response_model=list[WorkflowTransitionLogOut])
def get_instance_timeline(
    instance_id: int,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    """Retrieve immutable approval chain & event logs for a workflow instance."""
    inst = db.get(WorkflowInstance, instance_id)
    if not inst:
        raise HTTPException(status_code=404, detail="Workflow instance not found")
    logs = db.query(WorkflowTransitionLog).filter(
        WorkflowTransitionLog.instance_id == instance_id
    ).order_by(WorkflowTransitionLog.created_at.asc()).all()
    return logs




@router.get("/tasks", response_model=list[TaskOut])
def list_tasks(
    status: str | None = None,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    q = (
        db.query(Task, WorkflowInstance.document_id, User.username)
        .join(WorkflowInstance, Task.instance_id == WorkflowInstance.id)
        .outerjoin(User, Task.assignee_id == User.id)
    )
    if user.role not in ("superadmin", "admin"):
        q = q.filter((Task.assignee_id == user.id) | (Task.assignee_role == user.role))
    if status:
        q = q.filter(Task.status == status)
    result = []
    for t, doc_id, username in q.order_by(Task.created_at.desc()).all():
        result.append(_format_task_out(t, doc_id, username))
    return result


@router.post("/tasks", response_model=TaskOut)
def create_task(
    payload: TaskCreate,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    if not payload.title or not payload.title.strip():
        raise HTTPException(status_code=400, detail="Task title is required")

    doc_id = payload.document_id
    if doc_id is not None:
        d = db.get(Document, doc_id)
        if not d:
            raise HTTPException(status_code=404, detail="Document not found")
        f = db.get(Folder, d.folder_id)
        if not has_permission(db, user, "read", f, d):
            raise HTTPException(status_code=403, detail="No permission on document")
    else:
        first_doc = db.query(Document).first()
        if first_doc:
            doc_id = first_doc.id
        else:
            root_f = db.query(Folder).filter(Folder.parent_id == None).first()
            if not root_f:
                root_f = Folder(name="General", created_by=user.id)
                db.add(root_f)
                db.flush()
            placeholder = Document(
                folder_id=root_f.id,
                title="General Workspace",
                file_path="",
                size=0,
                created_by=user.id,
                status="ready",
            )
            db.add(placeholder)
            db.flush()
            doc_id = placeholder.id

    tmpl = db.query(WorkflowTemplate).filter(WorkflowTemplate.name == "Ad-hoc Tasks").first()
    if not tmpl:
        tmpl = WorkflowTemplate(
            name="Ad-hoc Tasks",
            description="Template for ad-hoc and user-created tasks",
            steps=[{"name": "Review & Complete", "assignee_role": "user"}],
            created_by=user.id,
        )
        db.add(tmpl)
        db.flush()

    inst = WorkflowInstance(
        template_id=tmpl.id,
        document_id=doc_id,
        status="running",
        current_step=0,
        context={"task_title": payload.title.strip()},
        created_by=user.id,
    )
    db.add(inst)
    db.flush()

    assignee_id = payload.assignee_id or user.id
    assignee_user = db.get(User, assignee_id) if assignee_id else user
    assignee_name = assignee_user.username if assignee_user else user.username

    due = payload.due_at
    if not due and payload.sla_hours:
        due = now() + timedelta(hours=payload.sla_hours)

    task = Task(
        instance_id=inst.id,
        step_index=0,
        step_name=payload.title.strip(),
        assignee_id=assignee_id,
        assignee_role=payload.assignee_role,
        comment=payload.description or "",
        sla_hours=payload.sla_hours,
        due_at=due,
        status="pending",
    )
    db.add(task)
    db.flush()

    target_uid = assignee_id if assignee_id else user.id
    notif = Notification(
        user_id=target_uid,
        message=f"New Task: {payload.title.strip()} (Doc #{doc_id})",
        read=False,
    )
    db.add(notif)
    db.commit()
    db.refresh(task)

    audit(db, user, "TASK_CREATE", "task", task.id, payload.title.strip())
    return _format_task_out(task, doc_id, assignee_name)


@router.post("/tasks/{task_id}/action", response_model=TaskOut)
def task_action(
    task_id: int,
    payload: TaskAction,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    t = db.get(Task, task_id)
    if not t:
        raise HTTPException(status_code=404, detail="Task not found")
    inst = db.get(WorkflowInstance, t.instance_id)
    if not inst:
        raise HTTPException(status_code=404, detail="Instance not found")

    may_act = (
        t.assignee_id == user.id
        or t.assignee_role == user.role
        or user.role in ("superadmin", "admin")
        or (t.assignee_id is None and inst.created_by == user.id)
    )
    if not may_act:
        raise HTTPException(status_code=403, detail="Not assigned to you")
    if t.status != "pending":
        raise HTTPException(status_code=400, detail="Task already resolved")

    act = payload.action or ("approve" if payload.approved else "reject")
    try:
        res = advance_task(
            db=db,
            task_id=task_id,
            action=act,
            user_id=user.id,
            comment=payload.comment or "",
            form_data=payload.form_data or {},
            signature=payload.signature,
            reassign_to_id=payload.reassign_to_id,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    db.refresh(t)
    assignee = db.get(User, t.assignee_id)
    audit(db, user, "WORKFLOW_ACTION", "task", t.id, f"{t.status} step {t.step_name}")
    return _format_task_out(t, inst.document_id, assignee.username if assignee else None)


@router.post("/workflows/check-slas")
def trigger_sla_escalation(
    db: Session = Depends(get_db),
    user: User = Depends(require_role("superadmin", "admin")),
):
    """Scan and execute SLA auto-escalation on overdue workflow tasks."""
    escalated = check_and_escalate_slas(db)
    return {"ok": True, "escalated_count": len(escalated), "details": escalated}


def _format_task_out(t: Task, doc_id: int | None, username: str | None) -> dict:
    return {
        "id": t.id,
        "instance_id": t.instance_id,
        "step_index": t.step_index,
        "step_name": t.step_name,
        "routing_type": t.routing_type or "sequential",
        "assignee_id": t.assignee_id,
        "assignee_role": t.assignee_role,
        "assignee_username": username,
        "document_id": doc_id,
        "status": t.status,
        "action_taken": t.action_taken,
        "comment": t.comment,
        "form_data": t.form_data,
        "form_schema": t.form_schema,
        "signature": t.signature,
        "sla_hours": t.sla_hours,
        "escalated": t.escalated,
        "escalated_to_id": t.escalated_to_id,
        "escalated_at": t.escalated_at,
        "node_id": t.node_id,
        "due_at": t.due_at,
        "completed_at": t.completed_at,
        "created_at": t.created_at,
    }


@router.get("/notifications", response_model=list[NotificationOut])
def list_notifications(
    unread_only: bool = False,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    q = db.query(Notification).filter(Notification.user_id == user.id)
    if unread_only:
        q = q.filter(Notification.read.is_(False))
    return q.order_by(Notification.created_at.desc()).limit(100).all()


@router.post("/notifications/{notif_id}/read")
def mark_read(
    notif_id: int,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    n = db.get(Notification, notif_id)
    if not n or n.user_id != user.id:
        raise HTTPException(status_code=404, detail="Notification not found")
    n.read = True
    db.commit()
    return {"ok": True}


@router.post("/notifications/read-all")
def mark_all_read(
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    db.query(Notification).filter(Notification.user_id == user.id, Notification.read.is_(False)).update(
        {"read": True}, synchronize_session=False
    )
    db.commit()
    return {"ok": True}
