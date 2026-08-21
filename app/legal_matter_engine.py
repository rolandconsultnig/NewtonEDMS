"""Legal Practice Matter engine: case lifecycle, conflict checks, and ethical wall enforcement."""
from __future__ import annotations

import logging
from typing import Any

from fastapi import HTTPException, status
from sqlalchemy.orm import Session

from app.database import now
from app.models import Document, EthicalWall, Matter, MatterDocument, User

logger = logging.getLogger("newtonedms.legal.matter")


def is_user_walled(db: Session, user_id: int, matter_id: int) -> bool:
    """Check if a user is barred from accessing a matter due to an ethical wall."""
    walls = db.query(EthicalWall).filter(
        EthicalWall.matter_id == matter_id,
        EthicalWall.active.is_(True),
    ).all()

    if not walls:
        return False

    for wall in walls:
        walled_users = wall.walled_user_ids or []
        if user_id in walled_users or str(user_id) in [str(u) for u in walled_users]:
            return True

    return False


def enforce_ethical_wall(db: Session, user: User, matter_id: int) -> None:
    """Raise 403 Forbidden if user is subject to an active ethical wall on this matter."""
    if user.role == "superadmin":
        # Superadmins may audit ethical walls, but can still be subject if strict compliance requires
        pass
    if is_user_walled(db, user.id, matter_id):
        logger.warning("Ethical wall breach attempt: User %s (id=%d) on Matter %d", user.username, user.id, matter_id)
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Access restricted: You are subject to an active Ethical Wall conflict policy on this matter.",
        )


def enforce_document_ethical_wall(db: Session, user: User, document_id: int) -> None:
    """Check if document belongs to any matter where user is walled off."""
    links = db.query(MatterDocument).filter(MatterDocument.document_id == document_id).all()
    for link in links:
        enforce_ethical_wall(db, user, link.matter_id)


def create_matter(
    db: Session,
    user: User,
    matter_number: str,
    title: str,
    client_name: str,
    client_id: str | None = None,
    practice_area: str = "General Litigation",
    lead_attorney_id: int | None = None,
    court_name: str | None = None,
    case_caption: str | None = None,
    judge_name: str | None = None,
    opposing_counsel: str | None = None,
    billing_code: str | None = None,
    description: str | None = None,
    metadata_json: dict[str, Any] | None = None,
) -> Matter:
    """Create a new legal matter."""
    existing = db.query(Matter).filter(Matter.matter_number.ilike(matter_number.strip())).first()
    if existing:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Matter with number '{matter_number}' already exists.",
        )

    matter = Matter(
        matter_number=matter_number.strip().upper(),
        title=title.strip(),
        client_name=client_name.strip(),
        client_id=client_id.strip() if client_id else None,
        practice_area=practice_area,
        lead_attorney_id=lead_attorney_id or user.id,
        court_name=court_name,
        case_caption=case_caption,
        judge_name=judge_name,
        opposing_counsel=opposing_counsel,
        billing_code=billing_code,
        description=description,
        metadata_json=metadata_json or {},
        created_by=user.id,
        created_at=now(),
        status="open",
    )
    db.add(matter)
    db.commit()
    db.refresh(matter)
    return matter


def attach_document_to_matter(
    db: Session,
    user: User,
    matter_id: int,
    document_id: int,
    category: str = "pleading",
    confidentiality: str = "confidential",
    bates_range: str | None = None,
    notes: str | None = None,
    pinned: bool = False,
) -> MatterDocument:
    """Associate a document with a matter under a legal category."""
    enforce_ethical_wall(db, user, matter_id)
    doc = db.get(Document, document_id)
    if not doc or doc.deleted_at is not None:
        raise HTTPException(status_code=404, detail="Document not found.")

    link = db.query(MatterDocument).filter(
        MatterDocument.matter_id == matter_id,
        MatterDocument.document_id == document_id,
    ).first()

    if link:
        link.category = category
        link.confidentiality = confidentiality
        link.bates_range = bates_range or link.bates_range
        link.notes = notes or link.notes
        link.pinned = pinned
    else:
        link = MatterDocument(
            matter_id=matter_id,
            document_id=document_id,
            category=category,
            confidentiality=confidentiality,
            bates_range=bates_range,
            notes=notes,
            pinned=pinned,
            added_by=user.id,
            added_at=now(),
        )
        db.add(link)

    # Also update document's matter_id reference
    if hasattr(doc, "matter_id"):
        doc.matter_id = matter_id

    db.commit()
    db.refresh(link)
    return link


def set_ethical_wall(
    db: Session,
    user: User,
    matter_id: int,
    walled_user_ids: list[int],
    reason: str,
    walled_group_ids: list[int] | None = None,
    client_name: str | None = None,
) -> EthicalWall:
    """Create or update an ethical wall policy for a matter."""
    matter = db.get(Matter, matter_id)
    if not matter:
        raise HTTPException(status_code=404, detail="Matter not found.")

    wall = db.query(EthicalWall).filter(EthicalWall.matter_id == matter_id).first()
    if not wall:
        wall = EthicalWall(
            matter_id=matter_id,
            client_name=client_name or matter.client_name,
            walled_user_ids=walled_user_ids,
            walled_group_ids=walled_group_ids or [],
            reason=reason,
            active=True,
            created_by=user.id,
            created_at=now(),
        )
        db.add(wall)
    else:
        wall.walled_user_ids = walled_user_ids
        wall.walled_group_ids = walled_group_ids or []
        wall.reason = reason
        wall.active = True

    db.commit()
    db.refresh(wall)
    return wall
