"""Workflow, tasks and notifications routes."""
from __future__ import annotations

from datetime import timedelta

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from app.audit import audit
from app.database import get_db, now
from app.models import Document, Folder, Notification, Task, User, WorkflowInstance, WorkflowTemplate
from app.permissions import has_permission
from app.schemas import (
    NotificationOut,
    TaskAction,
    TaskOut,
    WorkflowInstanceOut,
    WorkflowStep,
    WorkflowTemplateCreate,
    WorkflowTemplateOut,
)
from app.security import get_current_user, require_role

router = APIRouter(prefix="/api", tags=["workflow"])

VALID_ROLES = {"superadmin", "admin", "manager", "user"}


def _resolve_assignee(db: Session, step: WorkflowStep) -> User | None:
    """Find the assignee for a step by explicit id or by role."""
    if step.assignee_id:
        return db.get(User, step.assignee_id)
    if step.assignee_role and step.assignee_role in VALID_ROLES:
        return db.query(User).filter(User.role == step.assignee_role).first()
    return None


def _validated_steps(raw_steps) -> list[WorkflowStep]:
    """Validate freeform template steps against the WorkflowStep schema."""
    steps = [WorkflowStep.model_validate(s) for s in (raw_steps or [])]
    for step in steps:
        if not step.name or not step.name.strip():
            raise HTTPException(status_code=400, detail="Every workflow step needs a name")
        if not step.assignee_id and not step.assignee_role:
            raise HTTPException(
                status_code=400,
                detail=f"Step '{step.name}' has no assignee (assignee_id or assignee_role)",
            )
    return steps


def _create_task(db: Session, instance: WorkflowInstance, step_index: int, step: WorkflowStep):
    assignee = _resolve_assignee(db, step)
    due = now() + timedelta(days=step.due_days) if step.due_days else None
    t = Task(
        instance_id=instance.id,
        step_index=step_index,
        step_name=step.name,
        assignee_id=assignee.id if assignee else None,
        due_at=due,
    )
    db.add(t)
    db.flush()
    if assignee:
        db.add(
            Notification(
                user_id=assignee.id,
                message=f"New workflow task on document {instance.document_id}: {t.step_name}",
            )
        )
    return t


@router.get("/workflows", response_model=list[WorkflowTemplateOut])
def list_workflows(
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    return db.query(WorkflowTemplate).order_by(WorkflowTemplate.name).all()


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
        steps=[s.model_dump() for s in steps],
        created_by=user.id,
    )
    db.add(w)
    db.commit()
    db.refresh(w)
    audit(db, user, "WORKFLOW_CREATE", "workflow_template", w.id, w.name)
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
    # FK enforcement would turn this into a 500 once the template has been used.
    if db.query(WorkflowInstance).filter(WorkflowInstance.template_id == workflow_id).first():
        raise HTTPException(
            status_code=409, detail="Workflow has been used; deactivate it instead"
        )
    db.delete(w)
    db.commit()
    audit(db, user, "WORKFLOW_DELETE", "workflow_template", workflow_id, w.name)
    return {"ok": True}


@router.post("/documents/{doc_id}/workflows", response_model=WorkflowInstanceOut)
def start_workflow(
    doc_id: int,
    template_id: int,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    d = db.get(Document, doc_id)
    if not d:
        raise HTTPException(status_code=404, detail="Document not found")
    f = db.get(Folder, d.folder_id)
    if not has_permission(db, user, "write", f, d):
        raise HTTPException(status_code=403, detail="No permission")
    w = db.get(WorkflowTemplate, template_id)
    if not w:
        raise HTTPException(status_code=404, detail="Workflow template not found")
    # A document runs at most one workflow at a time (concurrent instances would
    # both mutate its status).
    if (
        db.query(WorkflowInstance)
        .filter(WorkflowInstance.document_id == doc_id, WorkflowInstance.status == "running")
        .first()
    ):
        raise HTTPException(status_code=409, detail="A workflow is already running on this document")
    steps = _validated_steps(w.steps)
    if not steps:
        raise HTTPException(status_code=400, detail="Workflow has no steps")
    # Refuse to start if the first step cannot be assigned: an unassigned task
    # can never be acted on and would deadlock the workflow.
    if not _resolve_assignee(db, steps[0]):
        raise HTTPException(
            status_code=400, detail=f"Step '{steps[0].name}' has no assignable user"
        )
    inst = WorkflowInstance(
        template_id=w.id,
        document_id=doc_id,
        status="running",
        current_step=0,
        created_by=user.id,
    )
    db.add(inst)
    db.flush()
    _create_task(db, inst, 0, steps[0])
    if d.status == "draft":
        d.status = "review"
        d.updated_at = now()
    db.commit()
    db.refresh(inst)
    audit(db, user, "WORKFLOW_START", "workflow_instance", inst.id, f"Template {w.id} on document {doc_id}")
    return inst


@router.get("/workflow-instances", response_model=list[WorkflowInstanceOut])
def list_instances(
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    q = db.query(WorkflowInstance)
    if user.role not in ("superadmin", "admin"):
        q = q.filter(WorkflowInstance.created_by == user.id)
    return q.order_by(WorkflowInstance.created_at.desc()).all()


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
        q = q.filter(Task.assignee_id == user.id)
    if status:
        q = q.filter(Task.status == status)
    result = []
    for t, doc_id, username in q.order_by(Task.created_at.desc()).all():
        result.append({
            "id": t.id,
            "instance_id": t.instance_id,
            "step_index": t.step_index,
            "step_name": t.step_name,
            "assignee_id": t.assignee_id,
            "assignee_username": username,
            "document_id": doc_id,
            "status": t.status,
            "comment": t.comment,
            "due_at": t.due_at,
            "completed_at": t.completed_at,
            "created_at": t.created_at,
        })
    return result


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
    # Unassigned tasks (e.g. role with no users) can be acted on by the
    # instance creator or admins so the workflow cannot deadlock.
    may_act = t.assignee_id == user.id or user.role in ("superadmin", "admin") or (
        t.assignee_id is None and inst and inst.created_by == user.id
    )
    if not may_act:
        raise HTTPException(status_code=403, detail="Not assigned to you")
    if t.status != "pending":
        raise HTTPException(status_code=400, detail="Task already resolved")

    d = db.get(Document, inst.document_id)
    # The actor must still be able to read the document being approved.
    f = db.get(Folder, d.folder_id)
    if not has_permission(db, user, "read", f, d):
        raise HTTPException(status_code=403, detail="No permission")

    # Atomically claim the pending task so two concurrent actions cannot both
    # advance the workflow (double-increment / skipped steps).
    claimed = (
        db.query(Task)
        .filter(Task.id == task_id, Task.status == "pending")
        .update(
            {
                Task.status: "approved" if payload.approved else "rejected",
                Task.completed_at: now(),
            },
            synchronize_session=False,
        )
    )
    if not claimed:
        db.rollback()
        raise HTTPException(status_code=400, detail="Task already resolved")
    db.refresh(t)

    steps = _validated_steps(db.get(WorkflowTemplate, inst.template_id).steps)

    t.comment = payload.comment or ""

    if payload.approved:
        inst.current_step += 1
        if inst.current_step >= len(steps):
            inst.status = "completed"
            inst.completed_at = now()
            d.status = "approved"
            d.updated_at = now()
            db.add(Notification(user_id=inst.created_by, message=f"Workflow completed for document {d.id}"))
        else:
            _create_task(db, inst, inst.current_step, steps[inst.current_step])
            d.status = "review"
            d.updated_at = now()
    else:
        inst.status = "rejected"
        inst.completed_at = now()
        d.status = "draft"
        d.updated_at = now()
        db.add(Notification(user_id=inst.created_by, message=f"Workflow rejected for document {d.id}"))

    db.commit()
    db.refresh(t)
    assignee = db.get(User, t.assignee_id)
    audit(db, user, "WORKFLOW_ACTION", "task", t.id, f"{t.status} step {t.step_name}")
    return {
        "id": t.id,
        "instance_id": t.instance_id,
        "step_index": t.step_index,
        "step_name": t.step_name,
        "assignee_id": t.assignee_id,
        "assignee_username": assignee.username if assignee else None,
        "document_id": d.id,
        "status": t.status,
        "comment": t.comment,
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
