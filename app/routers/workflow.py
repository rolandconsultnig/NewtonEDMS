"""Workflow, tasks and notifications routes."""
from __future__ import annotations

from datetime import timedelta
from typing import Optional

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
    WorkflowTemplateCreate,
    WorkflowTemplateOut,
)
from app.security import get_current_user, require_role

router = APIRouter(prefix="/api", tags=["workflow"])


def _resolve_assignee(db: Session, step: dict) -> Optional[User]:
    """Find the assignee for a step by explicit id or by role."""
    if step.get("assignee_id"):
        return db.get(User, int(step["assignee_id"]))
    role = step.get("assignee_role")
    if role:
        return db.query(User).filter(User.role == role).first()
    return None


def _create_task(db: Session, instance: WorkflowInstance, step_index: int, step: dict):
    assignee = _resolve_assignee(db, step)
    due_days = step.get("due_days")
    due = now() + timedelta(days=due_days) if due_days else None
    t = Task(
        instance_id=instance.id,
        step_index=step_index,
        step_name=step.get("name", f"Step {step_index + 1}"),
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
    w = WorkflowTemplate(
        name=payload.name,
        description=payload.description,
        steps=payload.steps or [],
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
    steps = w.steps or []
    if not steps:
        raise HTTPException(status_code=400, detail="Workflow has no steps")
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
    status: Optional[str] = None,
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
    if t.assignee_id != user.id and user.role not in ("superadmin", "admin"):
        raise HTTPException(status_code=403, detail="Not assigned to you")
    if t.status != "pending":
        raise HTTPException(status_code=400, detail="Task already resolved")

    inst = db.get(WorkflowInstance, t.instance_id)
    steps = db.get(WorkflowTemplate, inst.template_id).steps or []
    d = db.get(Document, inst.document_id)

    t.comment = payload.comment or ""
    t.completed_at = now()

    if payload.approved:
        t.status = "approved"
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
        t.status = "rejected"
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
        q = q.filter(Notification.read == False)
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
