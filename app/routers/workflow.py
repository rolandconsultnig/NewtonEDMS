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


def _create_task(db: Session, instance: WorkflowInstance, step_index: int, step: WorkflowStep, node_id: str | None = None):
    assignee = _resolve_assignee(db, step)
    due = now() + timedelta(days=step.due_days) if step.due_days else None
    t = Task(
        instance_id=instance.id,
        step_index=step_index,
        step_name=step.name,
        assignee_id=assignee.id if assignee else None,
        due_at=due,
        node_id=node_id,
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


def _graph_definition(template: WorkflowTemplate):
    from app.bpmn import from_graph_json

    graph = template.graph or {}
    if not (graph.get("nodes") or graph.get("edges")):
        return None
    return from_graph_json(graph, template.steps)


def _run_service_task(db: Session, doc: Document, node) -> None:
    action = (node.action or "").lower()
    if action == "watermark":
        from pathlib import Path
        from app.pdfops import watermark
        from app.storage import doc_storage_dir

        src = Path(doc.pdf_file_path or doc.file_path)
        if src.exists():
            dest = doc_storage_dir(doc.id) / "watermarked.pdf"
            watermark(src, dest, "WORKFLOW")
            doc.pdf_file_path = str(dest)
    elif action == "archive":
        doc.status = "archived"
    elif action == "approve":
        doc.status = "approved"


def _close_bpmn_case(db: Session, template: WorkflowTemplate | None) -> None:
    """When a BPMN-backed workflow finishes, close matching cases."""
    if not template or not (template.name or "").startswith("bpmn:"):
        return
    try:
        bpmn_id = int(template.name.split(":", 1)[1])
    except (TypeError, ValueError):
        return
    from app.models import Case

    for case in db.query(Case).filter(Case.bpmn_id == bpmn_id, Case.status != "closed").all():
        case.status = "closed"
        case.closed_at = now()


def _advance_graph(db: Session, inst: WorkflowInstance, template: WorkflowTemplate, from_node: str, context: dict, approved: bool = True) -> None:
    from app.bpmn import next_nodes

    d = db.get(Document, inst.document_id)
    definition = _graph_definition(template)
    if not definition:
        return
    if not approved:
        inst.status = "rejected"
        inst.completed_at = now()
        if d:
            d.status = "draft"
            d.updated_at = now()
            db.add(Notification(user_id=inst.created_by, message=f"Workflow rejected for document {d.id}"))
        return
    queue = list(next_nodes(definition, from_node, context))
    seen: set[str] = set()
    pending = []
    while queue:
        nid = queue.pop(0)
        if nid in seen:
            continue
        seen.add(nid)
        node = definition.nodes.get(nid)
        if not node or node.type in ("end", "endEvent"):
            continue
        if node.type in ("start", "startEvent", "exclusiveGateway", "parallelGateway"):
            queue.extend(next_nodes(definition, nid, context))
            continue
        if node.type == "serviceTask":
            if d:
                _run_service_task(db, d, node)
            queue.extend(next_nodes(definition, nid, context))
            continue
        pending.append(node)
    if not pending:
        inst.status = "completed"
        inst.completed_at = now()
        if d:
            d.status = "approved"
            d.updated_at = now()
            db.add(Notification(user_id=inst.created_by, message=f"Workflow completed for document {d.id}"))
        _close_bpmn_case(db, template)
        return
    inst.current_node = pending[0].id
    inst.tokens = [n.id for n in pending]
    for node in pending:
        step = WorkflowStep(
            name=node.name,
            assignee_role=node.assignee_role,
            assignee_id=node.assignee_id,
            due_days=node.due_days,
        )
        inst.current_step = (inst.current_step or 0) + 1
        _create_task(db, inst, inst.current_step, step, node_id=node.id)
    if d:
        d.status = "review"
        d.updated_at = now()


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
    definition = _graph_definition(w)
    inst = WorkflowInstance(
        template_id=w.id,
        document_id=doc_id,
        status="running",
        current_step=0,
        created_by=created_by,
    )
    db.add(inst)
    db.flush()
    if definition and definition.start:
        inst.current_node = definition.start
        context = {"status": d.status, "tags": d.tags or "", "approved": "true"}
        _advance_graph(db, inst, w, definition.start, context, approved=True)
    else:
        try:
            steps = _validated_steps(w.steps)
        except HTTPException as exc:
            raise ValueError(exc.detail) from exc
        if not steps:
            raise ValueError("Workflow has no steps")
        if not _resolve_assignee(db, steps[0]):
            raise ValueError(f"Step '{steps[0].name}' has no assignable user")
        _create_task(db, inst, 0, steps[0])
        if d.status == "draft":
            d.status = "review"
            d.updated_at = now()
    db.commit()
    db.refresh(inst)
    return inst


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
    try:
        inst = start_workflow_internal(db, doc_id, template_id, created_by=user.id)
    except ValueError as exc:
        msg = str(exc)
        code = 409 if "already running" in msg else 400
        raise HTTPException(status_code=code, detail=msg) from exc
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
            "node_id": t.node_id,
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

    tpl = db.get(WorkflowTemplate, inst.template_id)
    definition = _graph_definition(tpl) if tpl else None
    steps = []
    if not definition:
        steps = _validated_steps(tpl.steps if tpl else [])

    t.comment = payload.comment or ""
    if definition and (t.node_id or inst.current_node):
        context = {
            "status": d.status,
            "tags": d.tags or "",
            "approved": "true" if payload.approved else "false",
            "decision": "approved" if payload.approved else "rejected",
        }
        _advance_graph(db, inst, tpl, t.node_id or inst.current_node, context, approved=payload.approved)
    elif payload.approved:
        inst.current_step += 1
        if inst.current_step >= len(steps):
            inst.status = "completed"
            inst.completed_at = now()
            d.status = "approved"
            d.updated_at = now()
            db.add(Notification(user_id=inst.created_by, message=f"Workflow completed for document {d.id}"))
            _close_bpmn_case(db, tpl)
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
