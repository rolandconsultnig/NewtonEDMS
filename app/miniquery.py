"""JSON mini-query used to filter notification events and public shares.

Supported shapes::

    {"tag": "invoice"}
    {"status": "draft", "year": 2026}
    {"and": [{"tag": "invoice"}, {"not": {"tag": "paid"}}]}
    {"or": [{"corr.org": "acme"}, {"cat": "finance"}]}
"""
from __future__ import annotations

from datetime import datetime, timedelta
from typing import Any

from sqlalchemy.orm import Session

from app.models import Contact, CustomField, CustomFieldValue, Document, Equipment, Organization, Tag


def _doc_tags(doc: Document) -> set[str]:
    return {t.strip().lower() for t in (doc.tags or "").split(",") if t.strip()}


def _match_clause(db: Session, doc: Document, field: str, value: Any) -> bool:
    field = field.lower()
    sval = "" if value is None else str(value)
    if field in ("tag", "tags"):
        return sval.lower() in _doc_tags(doc)
    if field == "status":
        return (doc.status or "") == sval
    if field == "source":
        return (doc.source or "") == sval
    if field in ("lang", "language"):
        return (doc.language or "") == sval
    if field == "year":
        dt = doc.item_date or doc.created_at
        return bool(dt) and dt.year == int(value)
    if field == "cat":
        names = _doc_tags(doc)
        rows = db.query(Tag).filter(Tag.category.ilike(sval)).all()
        return any(t.name.lower() in names for t in rows)
    if field in ("corr.org", "organization"):
        if doc.organization_id:
            org = db.get(Organization, doc.organization_id)
            if org and sval.lower() in (org.name or "").lower():
                return True
        if doc.correspondent_id:
            c = db.get(Contact, doc.correspondent_id)
            return bool(c and sval.lower() in ((c.organization or "") + " " + (c.name or "")).lower())
        return False
    if field in ("corr.pers", "correspondent"):
        if not doc.correspondent_id:
            return False
        c = db.get(Contact, doc.correspondent_id)
        return bool(c and sval.lower() in (c.name or "").lower())
    if field in ("conc.pers", "concerning"):
        if not doc.concerning_id:
            return False
        c = db.get(Contact, doc.concerning_id)
        return bool(c and sval.lower() in (c.name or "").lower())
    if field in ("conc.equip", "equipment"):
        if doc.equipment_id:
            eq = db.get(Equipment, doc.equipment_id)
            if eq and sval.lower() in (eq.name or "").lower():
                return True
        return sval.lower() in (doc.equipment or "").lower()
    if field == "confirmed":
        want = str(value).lower() in ("1", "true", "yes")
        return bool(doc.confirmed) is want
    if field.startswith("f:") or field.startswith("f."):
        fname = field.split(":", 1)[-1] if ":" in field else field.split(".", 1)[-1]
        fld = db.query(CustomField).filter(CustomField.name == fname).first()
        if not fld:
            return False
        row = (
            db.query(CustomFieldValue)
            .filter(CustomFieldValue.field_id == fld.id, CustomFieldValue.document_id == doc.id)
            .first()
        )
        if value in ("*", True):
            return row is not None and bool(row.value)
        return bool(row) and sval.lower() in (row.value or "").lower()
    if field == "id":
        return doc.id == int(value)
    if field == "folder":
        return doc.folder_id == int(value)
    hay = " ".join(
        filter(
            None,
            [doc.title, doc.name, doc.notes, doc.extracted_text, doc.tags],
        )
    ).lower()
    return sval.lower() in hay


def match(db: Session, doc: Document, spec: Any) -> bool:
    """Return True if ``doc`` satisfies the mini-query ``spec``."""
    if not spec:
        return True
    if isinstance(spec, str):
        from app.querylang import apply_filters, parse_query

        parsed = parse_query(spec)
        q = apply_filters(db.query(Document).filter(Document.id == doc.id), parsed, db)
        return q.first() is not None
    if not isinstance(spec, dict):
        return False
    if "and" in spec:
        return all(match(db, doc, part) for part in spec["and"])
    if "or" in spec:
        return any(match(db, doc, part) for part in spec["or"])
    if "not" in spec:
        return not match(db, doc, spec["not"])
    return all(_match_clause(db, doc, k, v) for k, v in spec.items())


def parse_date_expr(raw: str, *, relative_to: datetime | None = None) -> datetime | None:
    """Parse ``today``, ``now``, ``today;-7d``, ``today;+1m``, ISO dates."""
    relative_to = relative_to or datetime.utcnow()
    raw = (raw or "").strip()
    if not raw:
        return None
    if raw.lower() in ("today", "now"):
        if raw.lower() == "today":
            return relative_to.replace(hour=0, minute=0, second=0, microsecond=0)
        return relative_to
    if ";" in raw:
        base_s, delta_s = raw.split(";", 1)
        base = parse_date_expr(base_s, relative_to=relative_to)
        if base is None:
            return None
        delta_s = delta_s.strip()
        sign = 1
        if delta_s.startswith("+"):
            delta_s = delta_s[1:]
        elif delta_s.startswith("-"):
            sign = -1
            delta_s = delta_s[1:]
        if not delta_s:
            return base
        unit = delta_s[-1].lower()
        try:
            n = int(delta_s[:-1] or "0") * sign
        except ValueError:
            return base
        if unit == "d":
            return base + timedelta(days=n)
        if unit == "h":
            return base + timedelta(hours=n)
        if unit == "w":
            return base + timedelta(weeks=n)
        if unit == "m":
            return base + timedelta(days=30 * n)
        if unit == "y":
            return base + timedelta(days=365 * n)
        return base
    for fmt in ("%Y-%m-%d", "%Y-%m-%dT%H:%M", "%Y-%m-%dT%H:%M:%S", "%Y-%m"):
        try:
            return datetime.strptime(raw, fmt)
        except ValueError:
            continue
    return None
