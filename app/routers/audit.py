"""Enterprise Audit-log & Compliance Router (Admin & Manager)."""

import csv
import io
import json
from datetime import datetime, timedelta, timezone
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query, Request, Response
from fastapi.responses import StreamingResponse
from sqlalchemy import func, or_
from sqlalchemy.orm import Session

from app.audit import audit, calculate_audit_checksum
from app.database import get_db, now
from app.models import AuditLog, User
from app.schemas import AuditOut, AuditStatsOut, ClientSecurityEvent
from app.security import get_current_user, require_role

router = APIRouter(prefix="/api/audit", tags=["audit"])


@router.get("", response_model=list[AuditOut])
def list_audit(
    skip: int = 0,
    limit: int = 100,
    severity: str | None = None,
    status: str | None = None,
    action: str | None = None,
    resource_type: str | None = None,
    user_id: int | None = None,
    search: str | None = None,
    start_date: str | None = None,
    end_date: str | None = None,
    db: Session = Depends(get_db),
    user: User = Depends(require_role("superadmin", "admin", "manager")),
):
    """List and filter audit trail events."""
    q = db.query(AuditLog)

    if severity and severity.upper() != "ALL":
        q = q.filter(AuditLog.severity == severity.upper())
    if status and status.upper() != "ALL":
        q = q.filter(AuditLog.status == status.upper())
    if action and action.upper() != "ALL":
        q = q.filter(AuditLog.action.ilike(f"%{action}%"))
    if resource_type and resource_type.upper() != "ALL":
        q = q.filter(AuditLog.resource_type == resource_type.lower())
    if user_id:
        q = q.filter(AuditLog.user_id == user_id)
    if search:
        search_pattern = f"%{search}%"
        q = q.filter(
            or_(
                AuditLog.details.ilike(search_pattern),
                AuditLog.action.ilike(search_pattern),
                AuditLog.username.ilike(search_pattern),
                AuditLog.resource_name.ilike(search_pattern),
                AuditLog.ip.ilike(search_pattern),
            )
        )
    if start_date:
        try:
            sd = datetime.fromisoformat(start_date.replace("Z", "+00:00"))
            q = q.filter(AuditLog.timestamp >= sd)
        except Exception:
            pass
    if end_date:
        try:
            ed = datetime.fromisoformat(end_date.replace("Z", "+00:00"))
            q = q.filter(AuditLog.timestamp <= ed)
        except Exception:
            pass

    return q.order_by(AuditLog.timestamp.desc()).offset(skip).limit(limit).all()


@router.get("/stats", response_model=AuditStatsOut)
def get_audit_stats(
    db: Session = Depends(get_db),
    user: User = Depends(require_role("superadmin", "admin", "manager")),
):
    """Aggregated metrics and security KPIs for the Audit Dashboard."""
    total_events = db.query(func.count(AuditLog.id)).scalar() or 0
    today_start = now().replace(hour=0, minute=0, second=0, microsecond=0)
    today_events = (
        db.query(func.count(AuditLog.id))
        .filter(AuditLog.timestamp >= today_start)
        .scalar()
        or 0
    )

    security_alerts = (
        db.query(func.count(AuditLog.id))
        .filter(
            or_(
                AuditLog.severity.in_(["HIGH", "CRITICAL", "SECURITY_ALERT"]),
                AuditLog.status.in_(["DENIED", "FAILED", "SUSPICIOUS"]),
            )
        )
        .scalar()
        or 0
    )

    past_24h = now() - timedelta(hours=24)
    active_actors_24h = (
        db.query(func.count(func.distinct(AuditLog.username)))
        .filter(AuditLog.timestamp >= past_24h)
        .scalar()
        or 0
    )

    access_denials = (
        db.query(func.count(AuditLog.id))
        .filter(AuditLog.status == "DENIED")
        .scalar()
        or 0
    )

    # Severity distribution
    severity_rows = (
        db.query(AuditLog.severity, func.count(AuditLog.id))
        .group_by(AuditLog.severity)
        .all()
    )
    by_severity = {row[0] or "INFO": row[1] for row in severity_rows}

    # Top actions
    top_action_rows = (
        db.query(AuditLog.action, func.count(AuditLog.id).label("cnt"))
        .group_by(AuditLog.action)
        .order_by(func.count(AuditLog.id).desc())
        .limit(6)
        .all()
    )
    top_actions = [{"action": row[0], "count": row[1]} for row in top_action_rows]

    # Recent 6 hours trend
    recent_trend = []
    for i in range(6, -1, -1):
        slot_start = now() - timedelta(hours=i + 1)
        slot_end = now() - timedelta(hours=i)
        count = (
            db.query(func.count(AuditLog.id))
            .filter(AuditLog.timestamp >= slot_start, AuditLog.timestamp < slot_end)
            .scalar()
            or 0
        )
        recent_trend.append({"hour_label": f"-{i}h", "count": count})

    return AuditStatsOut(
        total_events=total_events,
        today_events=today_events,
        security_alerts=security_alerts,
        active_actors_24h=active_actors_24h,
        access_denials=access_denials,
        by_severity=by_severity,
        top_actions=top_actions,
        recent_trend=recent_trend,
    )


@router.get("/export")
def export_audit_log(
    format: str = Query("csv", regex="^(csv|json)$"),
    limit: int = 2000,
    db: Session = Depends(get_db),
    user: User = Depends(require_role("superadmin", "admin")),
):
    """Export compliance audit records to CSV or JSON."""
    logs = (
        db.query(AuditLog)
        .order_by(AuditLog.timestamp.desc())
        .limit(limit)
        .all()
    )

    # Record export event in audit trail
    audit(
        db,
        user,
        "AUDIT_EXPORT",
        resource_type="audit",
        resource_id=None,
        details=f"Exported {len(logs)} audit records in {format.upper()} format",
        severity="MEDIUM",
        status="SUCCESS",
    )

    if format == "json":
        export_data = [
            {
                "id": l.id,
                "timestamp": l.timestamp.isoformat() if l.timestamp else None,
                "username": l.username,
                "actor_role": l.actor_role,
                "action": l.action,
                "resource_type": l.resource_type,
                "resource_id": l.resource_id,
                "resource_name": l.resource_name,
                "severity": l.severity,
                "status": l.status,
                "details": l.details,
                "ip": l.ip,
                "user_agent": l.user_agent,
                "checksum": l.checksum,
            }
            for l in logs
        ]
        return Response(
            content=json.dumps({"records": export_data, "generated_at": now().isoformat()}, indent=2),
            media_type="application/json",
            headers={"Content-Disposition": f"attachment; filename=NewtonEDMS_AuditTrail_{now().strftime('%Y%m%d_%H%M%S')}.json"},
        )

    # CSV export
    output = io.StringIO()
    writer = csv.writer(output)
    writer.writerow([
        "ID",
        "Timestamp (UTC)",
        "Actor Username",
        "Actor Role",
        "Action",
        "Resource Type",
        "Resource ID",
        "Resource Name",
        "Severity",
        "Status",
        "Details",
        "Client IP",
        "User Agent",
        "SHA256 Checksum",
    ])
    for l in logs:
        writer.writerow([
            l.id,
            l.timestamp.isoformat() if l.timestamp else "",
            l.username or "",
            l.actor_role or "",
            l.action,
            l.resource_type or "",
            l.resource_id or "",
            l.resource_name or "",
            l.severity or "INFO",
            l.status or "SUCCESS",
            l.details or "",
            l.ip or "",
            l.user_agent or "",
            l.checksum or "",
        ])
    output.seek(0)
    return StreamingResponse(
        iter([output.getvalue()]),
        media_type="text/csv",
        headers={"Content-Disposition": f"attachment; filename=NewtonEDMS_AuditTrail_{now().strftime('%Y%m%d_%H%M%S')}.csv"},
    )


@router.post("/client-event")
def log_client_security_event(
    req: Request,
    payload: ClientSecurityEvent,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    """Log client-side security alerts or telemetry."""
    log = audit(
        db,
        user,
        action=f"CLIENT_{payload.event_type.upper()}",
        resource_type=payload.resource_type,
        resource_id=payload.resource_id,
        details=payload.details,
        request=req,
        severity=payload.severity.upper() if payload.severity else "WARNING",
        status="SUSPICIOUS" if "VIOLATION" in payload.event_type.upper() else "SUCCESS",
    )
    return {"ok": True, "audit_id": log.id}

