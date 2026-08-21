"""ProcessMaker Enterprise BPMN Workflow Engine.

Supports:
1. Automated Sequential & Parallel (all / any) Routing.
2. Conditional Decision Logic (Gateways: amount, department, tags, custom fields).
3. Dynamic Form & Metadata Capture per step.
4. Role-Based Access Control (RBAC) & Document State Transitions.
5. SLA Enforcement, Overdue Deadlines & Auto-Escalation.
6. Immutable Audit Trail & Transition Event Logging.
"""
from __future__ import annotations

import logging
from datetime import timedelta
from typing import Any

from sqlalchemy.orm import Session

from app.audit import audit
from app.bpmn import eval_condition, from_graph_json, next_nodes
from app.database import now
from app.models import (
    CustomField,
    CustomFieldValue,
    Document,
    Notification,
    Task,
    User,
    WorkflowInstance,
    WorkflowTemplate,
    WorkflowTransitionLog,
)

logger = logging.getLogger("newtonedms.workflow_engine")

VALID_ROLES = {"superadmin", "admin", "manager", "user", "compliance", "finance", "legal", "executive"}


def _resolve_assignees(db: Session, step: dict | Any) -> list[User]:
    """Resolve assignee user(s) by explicit ID, multiple IDs, or Role."""
    if isinstance(step, dict):
        aid = step.get("assignee_id")
        aids = step.get("assignee_ids") or []
        role = step.get("assignee_role")
    else:
        aid = getattr(step, "assignee_id", None)
        aids = getattr(step, "assignee_ids", []) or []
        role = getattr(step, "assignee_role", None)

    users: list[User] = []
    if aid:
        u = db.get(User, int(aid))
        if u:
            users.append(u)
    if aids:
        for x in aids:
            u = db.get(User, int(x))
            if u and u not in users:
                users.append(u)
    if not users and role:
        matching = db.query(User).filter(User.role == role, User.is_active == True).all()
        if matching:
            users.extend(matching)
    if not users:
        # Fallback to first active admin
        admin_u = db.query(User).filter(User.role.in_(["admin", "superadmin"])).first()
        if admin_u:
            users.append(admin_u)
    return users


def _build_context(db: Session, doc: Document, extra: dict | None = None) -> dict[str, Any]:
    """Construct complete execution context from document metadata, custom fields, and variables."""
    meta = getattr(doc, "metadata_json", {}) or {}
    if not isinstance(meta, dict):
        meta = {}
    tags_val = getattr(doc, "tags", "") or ""
    tags_list = [t.strip() for t in tags_val.split(",") if t.strip()] if isinstance(tags_val, str) else list(tags_val)

    ctx: dict[str, Any] = {
        "doc_id": doc.id,
        "title": doc.title or "",
        "filename": doc.title or "",
        "file_path": doc.file_path or "",
        "size": getattr(doc, "size", 0) or 0,
        "status": doc.status or "draft",
        "tags": tags_list,
        "created_by": doc.created_by,
        "department": meta.get("department", ""),
        "amount": 0.0,
    }
    ctx.update(meta)
    if "amount" in meta:
        try:
            ctx["amount"] = float(meta["amount"])
        except (ValueError, TypeError):
            pass

    # Extract custom field values
    cfvs = db.query(CustomFieldValue).filter(CustomFieldValue.document_id == doc.id).all()
    for cfv in cfvs:
        cf = db.get(CustomField, cfv.field_id)
        if cf:
            key = cf.name.lower().replace(" ", "_")
            ctx[key] = cfv.value
            if key in ("amount", "total", "budget", "cost"):
                try:
                    ctx["amount"] = float(cfv.value)
                except (ValueError, TypeError):
                    pass

    if extra:
        ctx.update(extra)
    return ctx


def start_workflow(
    db: Session,
    template_id: int,
    document_id: int,
    user_id: int,
    initial_variables: dict | None = None,
) -> WorkflowInstance:
    """Instantiate and execute initial stage of a ProcessMaker workflow."""
    template = db.get(WorkflowTemplate, template_id)
    if not template:
        raise ValueError("Workflow template not found")
    doc = db.get(Document, document_id)
    if not doc:
        raise ValueError("Document not found")
    user = db.get(User, user_id)

    context = _build_context(db, doc, initial_variables)

    instance = WorkflowInstance(
        template_id=template.id,
        document_id=doc.id,
        status="running",
        current_step=0,
        context=context,
        variables=initial_variables or {},
        created_by=user_id,
        created_at=now(),
    )
    db.add(instance)
    db.flush()

    # 1. Evaluate Auto-Approval Rule (e.g. amount < 1000)
    if template.auto_approval_rule and template.auto_approval_rule.strip():
        if eval_condition(template.auto_approval_rule, context):
            instance.status = "completed"
            instance.completed_at = now()
            doc.status = "approved"
            doc.updated_at = now()
            
            db.add(
                WorkflowTransitionLog(
                    instance_id=instance.id,
                    document_id=doc.id,
                    from_state="draft",
                    to_state="approved",
                    action="AUTO_APPROVE",
                    actor_id=user_id,
                    actor_name=(user.username if user else "system"),
                    comment=f"Auto-approved via rule: {template.auto_approval_rule}",
                    form_data=context,
                    created_at=now(),
                )
            )
            audit(db, user, "WORKFLOW_AUTO_APPROVE", "documents", doc.id, f"Auto-approved by rule {template.auto_approval_rule}")
            db.commit()
            return instance

    # 2. Dynamic RBAC: Document enters 'under_review', submitter locked to read-only
    doc.status = "under_review"
    doc.updated_at = now()

    # 3. Create Initial Routing Tasks
    routing = template.routing_type or "sequential"
    steps = template.steps or []

    # Check BPMN Graph
    if template.graph and (template.graph.get("nodes") or template.graph.get("edges")):
        definition = from_graph_json(template.graph, steps)
        if definition and definition.start:
            start_node = definition.nodes.get(definition.start)
            if start_node and start_node.type in ("start", "startEvent"):
                init_nids = next_nodes(definition, definition.start, context)
            else:
                init_nids = [definition.start]
            instance.current_node = init_nids[0] if init_nids else definition.start
            for nid in init_nids:
                node = definition.nodes.get(nid)
                if node and node.type == "userTask":
                    assignees = _resolve_assignees(db, node)
                    sla = (node.due_days * 24) if node.due_days else (template.sla_hours or 24)
                    for assignee in assignees:
                        _spawn_task(db, instance, 0, node.name, nid, assignee, routing, sla, template.form_schema)
    elif steps:
        step0 = steps[0] if isinstance(steps[0], dict) else {"name": str(steps[0])}
        due_d = step0.get("due_days") or 0
        sla = (due_d * 24) or (template.sla_hours or 24)
        assignees = _resolve_assignees(db, step0)
        for assignee in assignees:
            _spawn_task(db, instance, 0, step0.get("name", "Review Step 1"), "step_0", assignee, routing, sla, step0.get("form_schema") or template.form_schema)
    else:
        # Default single approval task
        assignees = _resolve_assignees(db, {"assignee_role": "admin"})
        for assignee in assignees:
            _spawn_task(db, instance, 0, "Document Approval", "step_0", assignee, routing, template.sla_hours or 24, template.form_schema)

    # Record Initial Transition Log
    db.add(
        WorkflowTransitionLog(
            instance_id=instance.id,
            document_id=doc.id,
            from_state="draft",
            to_state="under_review",
            action="SUBMIT",
            actor_id=user_id,
            actor_name=(user.username if user else "system"),
            comment="Submitted for workflow approval",
            form_data=initial_variables or {},
            created_at=now(),
        )
    )
    audit(db, user, "WORKFLOW_START", "documents", doc.id, f"Started workflow {template.name}")
    db.commit()
    return instance


def _spawn_task(
    db: Session,
    instance: WorkflowInstance,
    step_index: int,
    step_name: str,
    node_id: str,
    assignee: User | None,
    routing_type: str,
    sla_hours: int,
    form_schema: list | None = None,
) -> Task:
    """Create a pending task with SLA tracking and assignee notifications."""
    due = now() + timedelta(hours=sla_hours) if sla_hours else None
    task = Task(
        instance_id=instance.id,
        step_index=step_index,
        step_name=step_name,
        node_id=node_id,
        routing_type=routing_type,
        assignee_id=assignee.id if assignee else None,
        assignee_role=assignee.role if assignee else None,
        status="pending",
        sla_hours=sla_hours,
        due_at=due,
        form_schema=form_schema or [],
        created_at=now(),
    )
    db.add(task)
    db.flush()

    if assignee:
        db.add(
            Notification(
                user_id=assignee.id,
                message=f"New Task: [{step_name}] on Document #{instance.document_id} (SLA: {sla_hours}h)",
                created_at=now(),
            )
        )
    return task


def advance_task(
    db: Session,
    task_id: int,
    action: str,  # 'approve', 'reject', 'reassign', 'delegate'
    user_id: int,
    comment: str = "",
    form_data: dict | None = None,
    signature: str | None = None,
    reassign_to_id: int | None = None,
) -> dict:
    """Process a reviewer sign-off action, update forms, and advance state."""
    task = db.get(Task, task_id)
    if not task:
        raise ValueError("Task not found")
    if task.status != "pending":
        raise ValueError(f"Task already has status '{task.status}'")

    instance = db.get(WorkflowInstance, task.instance_id)
    if not instance:
        raise ValueError("Workflow instance not found")
    template = db.get(WorkflowTemplate, instance.template_id)
    doc = db.get(Document, instance.document_id)
    actor = db.get(User, user_id)

    action = action.lower().strip()
    form_data = form_data or {}

    # Store form data and signature into task
    task.form_data = form_data
    task.comment = comment
    task.signature = signature
    task.completed_at = now()
    task.action_taken = action

    # Propagate form data to document custom fields & context
    if form_data and doc:
        for k, v in form_data.items():
            # Check or create custom field
            cf = db.query(CustomField).filter(CustomField.name.ilike(k)).first()
            if not cf:
                cf = CustomField(name=k, label=k.replace("_", " ").title(), ftype="text", created_by=user_id)
                db.add(cf)
                db.flush()
            val_str = str(v)
            cfv = db.query(CustomFieldValue).filter(
                CustomFieldValue.document_id == doc.id,
                CustomFieldValue.field_id == cf.id,
            ).first()
            if cfv:
                cfv.value = val_str
            else:
                db.add(CustomFieldValue(document_id=doc.id, field_id=cf.id, value=val_str))
        instance.context = _build_context(db, doc, form_data)

    # 1. REASSIGN / DELEGATE
    if action in ("reassign", "delegate"):
        if not reassign_to_id:
            raise ValueError("Target assignee ID required for reassignment")
        target_u = db.get(User, reassign_to_id)
        if not target_u:
            raise ValueError("Target user not found")
        task.assignee_id = target_u.id
        task.assignee_role = target_u.role
        task.status = "pending"
        task.action_taken = None
        db.add(
            WorkflowTransitionLog(
                instance_id=instance.id,
                document_id=doc.id if doc else 0,
                task_id=task.id,
                from_state="under_review",
                to_state="under_review",
                action="REASSIGN",
                actor_id=user_id,
                actor_name=(actor.username if actor else "user"),
                comment=f"Reassigned to {target_u.username}: {comment}",
                form_data=form_data,
                signature=signature,
                created_at=now(),
            )
        )
        db.add(
            Notification(
                user_id=target_u.id,
                message=f"Task delegated to you: [{task.step_name}] on Document #{instance.document_id}",
                created_at=now(),
            )
        )
        db.commit()
        return {"status": "reassigned", "task_id": task.id, "assignee_id": target_u.id}

    # 2. REJECT
    if action == "reject":
        task.status = "rejected"
        instance.status = "rejected"
        instance.completed_at = now()
        if doc:
            doc.status = "draft"
            doc.updated_at = now()
            db.add(
                Notification(
                    user_id=instance.created_by,
                    message=f"Document #{doc.id} [{doc.title}] rejected by {actor.username if actor else 'reviewer'}: {comment}",
                    created_at=now(),
                )
            )
        db.add(
            WorkflowTransitionLog(
                instance_id=instance.id,
                document_id=doc.id if doc else 0,
                task_id=task.id,
                from_state="under_review",
                to_state="draft",
                action="REJECT",
                actor_id=user_id,
                actor_name=(actor.username if actor else "reviewer"),
                comment=comment,
                form_data=form_data,
                signature=signature,
                created_at=now(),
            )
        )
        audit(db, actor, "WORKFLOW_REJECT", "documents", doc.id if doc else 0, f"Task #{task.id} rejected: {comment}")
        db.commit()
        return {"status": "rejected", "instance_id": instance.id}

    # 3. APPROVE
    task.status = "approved"
    routing = task.routing_type or (template.routing_type if template else "sequential")

    # In parallel_any: mark all other parallel tasks as skipped
    if routing == "parallel_any":
        siblings = db.query(Task).filter(
            Task.instance_id == instance.id,
            Task.step_index == task.step_index,
            Task.id != task.id,
            Task.status == "pending",
        ).all()
        for sib in siblings:
            sib.status = "skipped"
            sib.completed_at = now()

    # In parallel_all: check if other peers are still pending
    if routing == "parallel_all":
        pending_peers = db.query(Task).filter(
            Task.instance_id == instance.id,
            Task.step_index == task.step_index,
            Task.id != task.id,
            Task.status == "pending",
        ).count()
        if pending_peers > 0:
            db.add(
                WorkflowTransitionLog(
                    instance_id=instance.id,
                    document_id=doc.id if doc else 0,
                    task_id=task.id,
                    from_state="under_review",
                    to_state="under_review",
                    action="APPROVE",
                    actor_id=user_id,
                    actor_name=(actor.username if actor else "approver"),
                    comment=f"Approved ({pending_peers} peer approvals remaining): {comment}",
                    form_data=form_data,
                    signature=signature,
                    created_at=now(),
                )
            )
            db.commit()
            return {"status": "waiting_for_peers", "remaining": pending_peers}

    # Log successful step approval
    db.add(
        WorkflowTransitionLog(
            instance_id=instance.id,
            document_id=doc.id if doc else 0,
            task_id=task.id,
            from_state="under_review",
            to_state="under_review",
            action="APPROVE",
            actor_id=user_id,
            actor_name=(actor.username if actor else "approver"),
            comment=comment,
            form_data=form_data,
            signature=signature,
            created_at=now(),
        )
    )

    # ADVANCE TO NEXT STEP / NODE
    _advance_to_next_stage(db, instance, template, doc, task.step_index, task.node_id)
    db.commit()
    return {"status": "advanced", "instance_id": instance.id, "current_step": instance.current_step}


def _advance_to_next_stage(
    db: Session,
    instance: WorkflowInstance,
    template: WorkflowTemplate | None,
    doc: Document | None,
    completed_step_index: int,
    completed_node_id: str | None,
) -> None:
    """Evaluate BPMN / sequential next step, conditional gateways, or complete workflow."""
    if not template:
        _finish_workflow(db, instance, doc)
        return

    context = instance.context or (getattr(doc, "metadata_json", {}) if doc else {})
    has_graph = bool(template.graph and (template.graph.get("nodes") or template.graph.get("edges")))

    if has_graph and completed_node_id:
        definition = from_graph_json(template.graph, template.steps)
        queue = list(next_nodes(definition, completed_node_id, context)) if definition else []
        seen: set[str] = set()
        spawned = False

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
                # Execute automated service task (e.g. watermark, archive)
                if doc:
                    action = (node.action or "").lower()
                    if action == "archive":
                        doc.status = "archived"
                    elif action == "approve":
                        doc.status = "approved"
                queue.extend(next_nodes(definition, nid, context))
                continue
            if node.type == "userTask":
                instance.current_node = nid
                instance.current_step = completed_step_index + 1
                assignees = _resolve_assignees(db, node)
                sla = (node.due_days * 24) if node.due_days else (template.sla_hours or 24)
                for assignee in assignees:
                    _spawn_task(
                        db, instance, instance.current_step, node.name, nid, assignee,
                        template.routing_type or "sequential", sla, template.form_schema
                    )
                spawned = True
                break

        if not spawned:
            _finish_workflow(db, instance, doc)
        return

    # Sequential Step Progression
    steps = template.steps or []
    next_index = completed_step_index + 1

    if next_index < len(steps):
        next_step = steps[next_index] if isinstance(steps[next_index], dict) else {"name": str(steps[next_index])}
        instance.current_step = next_index
        assignees = _resolve_assignees(db, next_step)
        sla = (next_step.get("due_days", 0) * 24) or (template.sla_hours or 24)
        for assignee in assignees:
            _spawn_task(
                db, instance, next_index, next_step.get("name", f"Step {next_index + 1}"),
                f"step_{next_index}", assignee, template.routing_type or "sequential", sla,
                next_step.get("form_schema") or template.form_schema
            )
    else:
        _finish_workflow(db, instance, doc)


def _finish_workflow(db: Session, instance: WorkflowInstance, doc: Document | None) -> None:
    """Finalize workflow with Approved status, read-only RBAC, and completion log."""
    instance.status = "completed"
    instance.completed_at = now()
    if doc:
        doc.status = "approved"
        doc.updated_at = now()
        db.add(
            Notification(
                user_id=instance.created_by,
                message=f"Workflow completed! Document #{doc.id} [{doc.title}] is now APPROVED.",
                created_at=now(),
            )
        )
    db.add(
        WorkflowTransitionLog(
            instance_id=instance.id,
            document_id=doc.id if doc else 0,
            from_state="under_review",
            to_state="approved",
            action="APPROVE",
            actor_name="workflow_engine",
            comment="All workflow stages successfully completed and approved.",
            created_at=now(),
        )
    )


def check_and_escalate_slas(db: Session) -> list[dict]:
    """Scan all active tasks, detect breached SLAs, and auto-escalate to designated roles."""
    breached_tasks = db.query(Task).filter(
        Task.status == "pending",
        Task.due_at != None,
        Task.due_at < now(),
        Task.escalated == False,
    ).all()

    escalated_results = []
    for task in breached_tasks:
        instance = db.get(WorkflowInstance, task.instance_id)
        template = db.get(WorkflowTemplate, instance.template_id) if instance else None
        doc = db.get(Document, instance.document_id) if instance else None

        esc_role = template.escalate_to_role if template and template.escalate_to_role else "manager"
        escalation_user = db.query(User).filter(User.role == esc_role, User.is_active == True).first()
        if not escalation_user:
            escalation_user = db.query(User).filter(User.role.in_(["admin", "superadmin"])).first()

        task.escalated = True
        task.escalated_at = now()
        if escalation_user:
            task.escalated_to_id = escalation_user.id
            task.assignee_id = escalation_user.id
            task.assignee_role = escalation_user.role

        db.add(
            WorkflowTransitionLog(
                instance_id=task.instance_id,
                document_id=doc.id if doc else 0,
                task_id=task.id,
                from_state="under_review",
                to_state="under_review",
                action="ESCALATE",
                actor_name="SLA_MONITOR",
                comment=f"SLA Breached: Task '{task.step_name}' overdue since {task.due_at}. Reassigned to {esc_role}.",
                created_at=now(),
            )
        )

        if escalation_user:
            db.add(
                Notification(
                    user_id=escalation_user.id,
                    message=f"URGENT: Task [{task.step_name}] on Doc #{doc.id if doc else ''} escalated to you due to SLA breach!",
                    created_at=now(),
                )
            )

        escalated_results.append({
            "task_id": task.id,
            "step_name": task.step_name,
            "document_id": doc.id if doc else None,
            "escalated_to": escalation_user.username if escalation_user else esc_role,
        })

    if escalated_results:
        db.commit()
    return escalated_results
