"""Hard multi-tenancy: stamp and filter folders/documents by collective."""
from __future__ import annotations

from sqlalchemy import or_
from sqlalchemy.orm import Query

from app.models import Document, Folder, User


def stamp(obj, user: User | None, parent: Folder | None = None) -> None:
    """Set collective_id on a new folder or document."""
    if getattr(obj, "collective_id", None):
        return
    cid = None
    if parent is not None:
        cid = getattr(parent, "collective_id", None)
    if cid is None and user is not None:
        cid = getattr(user, "collective_id", None)
    obj.collective_id = cid


def same_collective(user: User, *objs) -> bool:
    if user.role == "superadmin":
        return True
    cid = user.collective_id
    if not cid:
        return True
    for obj in objs:
        if obj is None:
            continue
        ocid = getattr(obj, "collective_id", None)
        if ocid is not None and ocid != cid:
            return False
    return True


def filter_query(q: Query, user: User, model) -> Query:
    """Restrict a Folder/Document query to the user's collective.

    Superadmin sees everything. Rows with NULL collective_id stay visible so
    the shared root and legacy data keep working.
    """
    if user.role == "superadmin":
        return q
    cid = user.collective_id
    if not cid:
        return q
    col = getattr(model, "collective_id", None)
    if col is None:
        return q
    return q.filter(or_(col == cid, col.is_(None)))


def filter_documents(q: Query, user: User) -> Query:
    return filter_query(q, user, Document)


def filter_folders(q: Query, user: User) -> Query:
    return filter_query(q, user, Folder)
