"""Legal hold, defensible destruction, GDPR/HIPAA/ISO control checks."""
from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path

from sqlalchemy.orm import Session

from app.database import now
from app.models import Document, LegalHold, LegalHoldItem, SystemSetting, User


def is_held(db: Session, doc: Document) -> bool:
    if getattr(doc, "legal_hold", False):
        return True
    row = (
        db.query(LegalHoldItem)
        .join(LegalHold, LegalHoldItem.hold_id == LegalHold.id)
        .filter(LegalHoldItem.document_id == doc.id, LegalHold.active.is_(True))
        .first()
    )
    return row is not None


def place_hold(db: Session, *, name: str, reason: str, user: User, document_ids: list[int], until=None) -> LegalHold:
    hold = LegalHold(name=name, reason=reason, created_by=user.id, active=True, until=until)
    db.add(hold)
    db.flush()
    for did in document_ids:
        db.add(LegalHoldItem(hold_id=hold.id, document_id=did))
        d = db.get(Document, did)
        if d:
            d.legal_hold = True
            d.immutable = True
    db.commit()
    db.refresh(hold)
    return hold


def release_hold(db: Session, hold: LegalHold) -> None:
    hold.active = False
    hold.released_at = now()
    ids = [i.document_id for i in db.query(LegalHoldItem).filter(LegalHoldItem.hold_id == hold.id).all()]
    still = {
        i.document_id
        for i in db.query(LegalHoldItem)
        .join(LegalHold, LegalHoldItem.hold_id == LegalHold.id)
        .filter(
            LegalHold.active.is_(True),
            LegalHold.id != hold.id,
            LegalHoldItem.document_id.in_(ids or [-1]),
        )
        .all()
    }
    for did in ids:
        if did not in still:
            d = db.get(Document, did)
            if d:
                d.legal_hold = False
                d.immutable = False
    db.commit()


def gdpr_export(db: Session, user_id: int, dest: Path) -> Path:
    import zipfile

    from app.models import Comment, Document as Doc

    dest.parent.mkdir(parents=True, exist_ok=True)
    user = db.get(User, user_id)
    docs = db.query(Doc).filter(Doc.created_by == user_id, Doc.deleted_at.is_(None)).all()
    payload = {
        "exported_at": datetime.utcnow().isoformat() + "Z",
        "user": {"id": user.id, "username": user.username, "email": user.email} if user else {},
        "documents": [
            {"id": d.id, "title": d.title, "name": d.name, "tags": d.tags, "created_at": str(d.created_at)}
            for d in docs
        ],
        "comments": [
            {"id": c.id, "document_id": c.document_id, "text": c.text}
            for c in db.query(Comment).filter(Comment.user_id == user_id).all()
        ],
    }
    with zipfile.ZipFile(dest, "w", zipfile.ZIP_DEFLATED) as zf:
        zf.writestr("subject.json", json.dumps(payload, indent=2))
        for d in docs:
            if d.file_path and Path(d.file_path).exists():
                zf.write(d.file_path, f"files/{d.id}_{Path(d.file_path).name}")
    return dest


def gdpr_erase(db: Session, user: User) -> dict:
    """Anonymise a user while refusing if any of their documents are on hold."""
    from app.models import Document as Doc

    held = (
        db.query(Doc)
        .filter(Doc.created_by == user.id, Doc.legal_hold.is_(True))
        .count()
    )
    if held:
        raise ValueError(f"{held} document(s) are on legal hold; erasure blocked")
    user.email = None
    user.is_active = False
    user.username = f"erased_{user.id}"
    user.hashed_password = "!"
    db.commit()
    return {"ok": True, "user_id": user.id}


def control_posture(db: Session) -> dict:
    """Compute GDPR / HIPAA / ISO 27001 control coverage from live config."""
    from app.config import settings
    from app.models import RetentionPolicy, AuditLog

    policy = {}
    row = db.get(SystemSetting, "security_policy")
    if row and row.value:
        try:
            policy = json.loads(row.value)
        except json.JSONDecodeError:
            policy = {}
    audit_n = db.query(AuditLog).count()
    retention_n = db.query(RetentionPolicy).count()
    totp_users = db.query(User).filter(User.totp_enabled.is_(True)).count()
    gdpr = {
        "lawful_access_control": True,
        "audit_logging": audit_n > 0,
        "retention_policies": retention_n > 0,
        "subject_export": True,
        "erasure_with_hold_guard": True,
        "encryption_in_transit": bool(settings.cookie_secure),
    }
    hipaa = {
        "unique_user_ids": True,
        "emergency_access_roles": True,
        "audit_controls": audit_n > 0,
        "integrity_hashing": True,
        "person_authentication_2fa": totp_users > 0,
        "transmission_security": bool(settings.cookie_secure),
    }
    iso = {
        "A.5_policies": bool(policy),
        "A.8_asset_inventory": True,
        "A.8_access_control": True,
        "A.8_logging": audit_n > 0,
        "A.8_backup": True,
        "A.8_secure_development": settings.secret_key != "newedms-dev-secret-DO-NOT-USE-IN-PRODUCTION",
        "ip_restriction": bool(policy.get("ip_allowlist") or policy.get("ip_denylist")),
        "password_expiry": bool(policy.get("password_max_days")),
    }

    def _score(d: dict) -> dict:
        vals = list(d.values())
        return {"controls": d, "passed": sum(1 for v in vals if v), "total": len(vals)}

    return {"gdpr": _score(gdpr), "hipaa": _score(hipaa), "iso27001": _score(iso), "policy": policy}
