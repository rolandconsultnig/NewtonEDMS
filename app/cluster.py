"""Cluster membership, heartbeats, and leader election for HA / load-balanced nodes."""
from __future__ import annotations

import os
import socket
from datetime import timedelta

from app import database
from app.database import now
from app.models import ClusterNode


def node_id() -> str:
    return os.environ.get("EDMS_NODE_ID") or f"{socket.gethostname()}:{os.getpid()}"


def heartbeat(role: str = "api") -> dict:
    db = database.SessionLocal()
    try:
        nid = node_id() if role == "api" else f"{node_id()}:{role}"
        row = db.query(ClusterNode).filter(ClusterNode.node_id == nid).first()
        if not row:
            row = ClusterNode(node_id=nid, role=role, host=socket.gethostname())
            db.add(row)
        row.last_seen = now()
        row.role = role
        row.alive = True
        # Expire stale nodes
        cutoff = now() - timedelta(seconds=45)
        db.query(ClusterNode).filter(ClusterNode.last_seen < cutoff).update({"alive": False})
        db.commit()
        # JOEX workers register separately and never become scheduler leader.
        leader = (
            db.query(ClusterNode)
            .filter(ClusterNode.alive.is_(True), ClusterNode.role != "joex")
            .order_by(ClusterNode.node_id.asc())
            .first()
        )
        return {
            "node_id": nid,
            "leader": leader.node_id if leader else nid,
            "is_leader": bool(leader and leader.node_id == nid),
        }
    finally:
        db.close()


def is_leader() -> bool:
    try:
        return bool(heartbeat("api").get("is_leader"))
    except Exception:
        return True


def members() -> list[dict]:
    db = database.SessionLocal()
    try:
        cutoff = now() - timedelta(seconds=45)
        rows = db.query(ClusterNode).order_by(ClusterNode.node_id).all()
        return [
            {
                "node_id": r.node_id,
                "role": r.role,
                "host": r.host,
                "alive": bool(r.alive and r.last_seen and r.last_seen >= cutoff),
                "last_seen": r.last_seen,
            }
            for r in rows
        ]
    finally:
        db.close()
