"""Folder/document access-control logic."""

from typing import List, Optional

from sqlalchemy import or_
from sqlalchemy.orm import Session

from app.models import Document, Folder, Permission, User


def _perm_column(action: str) -> str:
    return {
        "read": "can_read",
        "write": "can_write",
        "delete": "can_delete",
        "manage": "can_manage",
    }.get(action, "can_read")


def folder_chain(db: Session, folder: Folder) -> List[Folder]:
    chain = []
    current = folder
    while current:
        chain.append(current)
        if current.parent_id is None:
            break
        current = db.get(Folder, current.parent_id)
    return list(reversed(chain))


def has_permission(
    db: Session,
    user: User,
    action: str,
    folder: Folder,
    doc: Optional[Document] = None,
) -> bool:
    if user.role in ("superadmin", "admin"):
        return True
    if doc and doc.created_by == user.id:
        return True
    if folder and folder.created_by == user.id:
        return True
    # public read on folder or doc in public folder
    if action == "read":
        if doc and doc.folder and doc.folder.is_public:
            return True
        if folder and folder.is_public:
            return True
    resource_targets = []
    if doc:
        resource_targets.append(("document", doc.id))
    if folder:
        for f in folder_chain(db, folder):
            resource_targets.append(("folder", f.id))
    if not resource_targets:
        return False
    q = db.query(Permission).filter(
        Permission.resource_type.in_([r[0] for r in resource_targets]),
        Permission.resource_id.in_([r[1] for r in resource_targets]),
    ).filter(or_(*_principal_filters(user)))
    col = _perm_column(action)
    for p in q.all():
        if getattr(p, col):
            return True
    return False


def _principal_filters(user: User):
    filters = [(Permission.principal_type == "user") & (Permission.principal_id == user.id)]
    group_ids = [g.id for g in user.groups]
    if group_ids:
        filters.append(
            (Permission.principal_type == "group") & (Permission.principal_id.in_(group_ids))
        )
    return filters


def readable_folder_ids(db: Session, user: User) -> set:
    """Folders the user can read, resolved in O(folders + grants) rather than per document.

    A read grant on a folder is inherited by all of its descendants; public folders
    and folders the user owns are individually readable. Mirrors ``has_permission``
    for the "read" action so document visibility can be pushed into SQL.
    """
    children: dict = {}
    readable: set = set()
    for fid, pid, is_public, owner in db.query(
        Folder.id, Folder.parent_id, Folder.is_public, Folder.created_by
    ).all():
        if pid is not None:
            children.setdefault(pid, []).append(fid)
        if is_public or owner == user.id:
            readable.add(fid)
    granted = [
        row[0]
        for row in db.query(Permission.resource_id).filter(
            Permission.resource_type == "folder",
            Permission.can_read.is_(True),
            or_(*_principal_filters(user)),
        ).all()
    ]
    stack = list(granted)
    while stack:
        fid = stack.pop()
        if fid in readable:
            continue
        readable.add(fid)
        stack.extend(children.get(fid, []))
    return readable


def readable_document_ids(db: Session, user: User) -> set:
    return {
        row[0]
        for row in db.query(Permission.resource_id).filter(
            Permission.resource_type == "document",
            Permission.can_read.is_(True),
            or_(*_principal_filters(user)),
        ).all()
    }
