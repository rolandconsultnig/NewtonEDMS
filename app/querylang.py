"""Power search: AND / OR / NOT, operators, dotted fields, date arithmetic.

Examples::

    tag:invoice correspondent:acme due:overdue "purchase order"
    tag:invoice AND NOT tag:paid
    corr.org=Acme dateIn:today;-7d,today
    names:invoice OR content:acme
    f:amount>=100  checksum:abc  year:2026  cat:finance
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any

from sqlalchemy import and_, not_, or_
from sqlalchemy.orm import Session, Query as SAQuery

from app.miniquery import parse_date_expr
from app.models import (
    Contact,
    CustomField,
    CustomFieldValue,
    Document,
    DocumentAttachment,
    Equipment,
    Organization,
    Tag,
)

_TOKEN = re.compile(
    r"""
    (?P<op>\bAND\b|\bOR\b|\bNOT\b|\(|\))
    | (?P<field>[\w.]+)(?P<cmp>~=|>=|<=|!=|=|>|<|:)(?P<q>"[^"]*"|'[^']*'|\S+)
    | (?P<quoted>"[^"]+"|'[^']+')
    | (?P<word>\S+)
    """,
    re.VERBOSE | re.IGNORECASE,
)

FIELD_ALIASES = {
    "tag": "tags",
    "tags": "tags",
    "corr": "correspondent",
    "correspondent": "correspondent",
    "conc": "concerning",
    "concerning": "concerning",
    "lang": "language",
    "language": "language",
    "hash": "checksum",
    "checksum": "checksum",
    "name": "names",
    "names": "names",
    "content": "content",
    "inbox": "inbox",
}


@dataclass
class Clause:
    field: str
    op: str
    value: str
    negated: bool = False


@dataclass
class Node:
    kind: str  # and | or | not | clause | text
    children: list["Node"] = field(default_factory=list)
    clause: Clause | None = None
    text: str = ""


@dataclass
class ParsedQuery:
    filters: dict = field(default_factory=dict)
    fulltext: str = ""
    raw: str = ""
    tree: Node | None = None
    mode: str = "all"  # names | contents | all


class _Tok:
    def __init__(self, tokens: list[re.Match]):
        self.tokens = tokens
        self.i = 0

    def peek(self) -> re.Match | None:
        return self.tokens[self.i] if self.i < len(self.tokens) else None

    def take(self) -> re.Match | None:
        t = self.peek()
        if t is not None:
            self.i += 1
        return t


def parse_query(raw: str, mode: str = "all") -> ParsedQuery:
    raw = (raw or "").strip()
    tokens = list(_TOKEN.finditer(raw))
    stream = _Tok(tokens)
    tree = _parse_or(stream) if tokens else None
    filters: dict[str, Any] = {}
    words: list[str] = []
    _collect_simple(tree, filters, words)
    return ParsedQuery(
        filters=filters,
        fulltext=" ".join(words),
        raw=raw,
        tree=tree,
        mode=mode or "all",
    )


def _parse_or(s: _Tok) -> Node | None:
    left = _parse_and(s)
    while True:
        t = s.peek()
        if t is not None and t.group("op") and t.group("op").upper() == "OR":
            s.take()
            right = _parse_and(s)
            left = Node(kind="or", children=[c for c in (left, right) if c])
        else:
            break
    return left


def _parse_and(s: _Tok) -> Node | None:
    nodes: list[Node] = []
    while True:
        t = s.peek()
        if t is None:
            break
        if t.group("op") and t.group("op").upper() == "OR":
            break
        if t.group("op") and t.group("op") == ")":
            break
        if t.group("op") and t.group("op").upper() == "AND":
            s.take()
            continue
        node = _parse_not(s)
        if node is None:
            break
        nodes.append(node)
    if not nodes:
        return None
    if len(nodes) == 1:
        return nodes[0]
    return Node(kind="and", children=nodes)


def _parse_not(s: _Tok) -> Node | None:
    t = s.peek()
    if t is not None and t.group("op") and t.group("op").upper() == "NOT":
        s.take()
        inner = _parse_not(s)
        return Node(kind="not", children=[inner] if inner else [])
    return _parse_primary(s)


def _parse_primary(s: _Tok) -> Node | None:
    t = s.peek()
    if t is None:
        return None
    if t.group("op") == "(":
        s.take()
        inner = _parse_or(s)
        close = s.peek()
        if close is not None and close.group("op") == ")":
            s.take()
        return inner
    t = s.take()
    if t is None:
        return None
    if t.group("field"):
        field = t.group("field")
        op = t.group("cmp") or ":"
        val = t.group("q").strip("\"'")
        return Node(kind="clause", clause=Clause(field=field, op=op, value=val))
    if t.group("quoted"):
        return Node(kind="text", text=t.group("quoted").strip("\"'"))
    word = t.group("word") or ""
    if word.lower() == "inbox":
        return Node(kind="clause", clause=Clause(field="inbox", op=":", value="yes"))
    return Node(kind="text", text=word)


def _collect_simple(node: Node | None, filters: dict, words: list[str]) -> None:
    if node is None:
        return
    if node.kind == "text" and node.text:
        words.append(node.text)
        return
    if node.kind == "clause" and node.clause:
        c = node.clause
        key = c.field.lower()
        if key in ("tag", "tags"):
            filters.setdefault("tags", [])
            if isinstance(filters["tags"], list):
                filters["tags"].append(c.value)
        elif key in ("lang", "language"):
            filters["language"] = c.value
        elif key == "inbox":
            filters["inbox"] = c.value.lower() not in ("0", "no", "false")
        elif key == "correspondent":
            filters["correspondent"] = c.value
        elif key == "concerning":
            filters["concerning"] = c.value
        elif key == "due":
            filters["due"] = c.value
        elif key == "status":
            filters["status"] = c.value
        elif key == "folder":
            filters["folder"] = c.value
        elif key == "source":
            filters["source"] = c.value
        elif key == "id":
            filters["id"] = c.value
        elif key in ("name", "names"):
            filters["name"] = c.value
        elif key in ("hash", "checksum"):
            filters["hash"] = c.value
        elif key == "notes":
            filters["notes"] = c.value
        elif key == "custom":
            filters["custom"] = c.value
        elif key == "direction":
            filters["direction"] = c.value
        elif key == "equipment":
            filters["equipment"] = c.value
        elif key == "field":
            filters["field"] = c.value
        elif key == "color":
            filters["color"] = c.value
        elif key == "immutable":
            filters["immutable"] = c.value
        elif key == "locked":
            filters["locked"] = c.value
        else:
            filters[key] = c.value
        return
    for child in node.children:
        _collect_simple(child, filters, words)


def apply_filters(query: SAQuery, parsed: ParsedQuery, db: Session):
    """Apply structured filters. Uses the AST when present so AND/OR/NOT work."""
    if parsed.tree is not None:
        expr = _node_to_sql(parsed.tree, db, parsed)
        if expr is not None:
            query = query.filter(expr)
        return query
    return _apply_legacy(query, parsed, db)


def _node_to_sql(node: Node, db: Session, parsed: ParsedQuery):
    if node.kind == "and":
        parts = [p for p in (_node_to_sql(c, db, parsed) for c in node.children) if p is not None]
        if not parts:
            return None
        return and_(*parts)
    if node.kind == "or":
        parts = [p for p in (_node_to_sql(c, db, parsed) for c in node.children) if p is not None]
        if not parts:
            return None
        return or_(*parts)
    if node.kind == "not":
        inner = _node_to_sql(node.children[0], db, parsed) if node.children else None
        return not_(inner) if inner is not None else None
    if node.kind == "text":
        return _fulltext_expr(node.text, parsed.mode)
    if node.kind == "clause" and node.clause:
        return _clause_sql(node.clause, db)
    return None


def _fulltext_expr(text: str, mode: str):
    if not text:
        return None
    like = f"%{text}%"
    if mode == "names":
        return Document.name.ilike(like) | Document.title.ilike(like)
    if mode == "contents":
        return Document.extracted_text.ilike(like) | Document.notes.ilike(like)
    return (
        Document.name.ilike(like)
        | Document.title.ilike(like)
        | Document.tags.ilike(like)
        | Document.notes.ilike(like)
        | Document.extracted_text.ilike(like)
    )


def _cmp(column, op: str, value: str, *, numeric: bool = False, date: bool = False):
    if date:
        parsed = parse_date_expr(value)
        if parsed is None:
            parsed = value
        value = parsed
    elif numeric:
        try:
            value = float(value)
        except (TypeError, ValueError):
            pass
    if op in (":",):
        if hasattr(column, "ilike") and isinstance(value, str):
            return column.ilike(f"%{value}%")
        return column == value
    if op == "=":
        return column == value
    if op == "!=":
        return column != value
    if op == ">":
        return column > value
    if op == ">=":
        return column >= value
    if op == "<":
        return column < value
    if op == "<=":
        return column <= value
    if op == "~=":
        return column.op("REGEXP")(value) if isinstance(value, str) else column == value
    return column.ilike(f"%{value}%") if isinstance(value, str) else column == value


def _ids_for_name(db: Session, model, name: str) -> list[int]:
    rows = db.query(model).filter(model.name.ilike(f"%{name}%")).all()
    return [r.id for r in rows]


def _clause_sql(c: Clause, db: Session):
    from app.database import now

    field = c.field.lower()
    op, val = c.op, c.value
    if field in ("tag", "tags"):
        expr = Document.tags.ilike(f"%{val}%")
    elif field == "status":
        expr = _cmp(Document.status, op, val)
    elif field == "folder":
        try:
            expr = _cmp(Document.folder_id, "=" if op == ":" else op, val, numeric=True)
        except Exception:
            return None
    elif field == "source":
        expr = _cmp(Document.source, op, val)
    elif field in ("lang", "language"):
        expr = _cmp(Document.language, op, val)
    elif field == "id":
        expr = _cmp(Document.id, "=" if op == ":" else op, val, numeric=True)
    elif field in ("name", "names"):
        expr = Document.name.ilike(f"%{val}%") | Document.title.ilike(f"%{val}%")
    elif field == "content":
        expr = Document.extracted_text.ilike(f"%{val}%")
    elif field in ("hash", "checksum"):
        expr = Document.content_hash.ilike(f"{val}%")
    elif field == "notes":
        expr = Document.notes.ilike(f"%{val}%")
    elif field == "custom":
        expr = Document.custom_id.ilike(f"%{val}%")
    elif field == "direction":
        expr = _cmp(Document.direction, op, val)
    elif field in ("equipment", "conc.equip"):
        ids = _ids_for_name(db, Equipment, val)
        expr = Document.equipment.ilike(f"%{val}%")
        if ids:
            expr = expr | Document.equipment_id.in_(ids)
    elif field == "color":
        expr = _cmp(Document.color, op, val)
    elif field == "immutable":
        expr = Document.immutable.is_(val.lower() not in ("0", "no", "false"))
    elif field == "locked":
        expr = Document.locked_by.isnot(None) if val.lower() not in ("0", "no", "false") else Document.locked_by.is_(None)
    elif field == "inbox":
        expr = Document.processing_status != "done"
        if val.lower() in ("0", "no", "false"):
            expr = Document.processing_status == "done"
    elif field in ("correspondent", "corr.pers"):
        ids = _ids_for_name(db, Contact, val)
        expr = Document.correspondent_id.in_(ids or [-1])
    elif field in ("concerning", "conc.pers"):
        ids = _ids_for_name(db, Contact, val)
        expr = Document.concerning_id.in_(ids or [-1])
    elif field == "corr.org":
        org_ids = _ids_for_name(db, Organization, val)
        contact_ids = [
            c.id
            for c in db.query(Contact).filter(
                Contact.organization.ilike(f"%{val}%") | Contact.name.ilike(f"%{val}%")
            ).all()
        ]
        parts = []
        if org_ids:
            parts.append(Document.organization_id.in_(org_ids))
        if contact_ids:
            parts.append(Document.correspondent_id.in_(contact_ids))
        expr = or_(*parts) if parts else Document.id.in_([-1])
    elif field == "cat":
        tag_names = [t.name for t in db.query(Tag).filter(Tag.category.ilike(f"%{val}%")).all()]
        parts = [Document.tags.ilike(f"%{n}%") for n in tag_names] or [Document.id.in_([-1])]
        expr = or_(*parts)
    elif field == "confirmed":
        want = val.lower() not in ("0", "no", "false", "new")
        expr = Document.confirmed.is_(want)
        if val.lower() == "new":
            expr = Document.confirmed.is_(False)
    elif field == "year":
        try:
            year = int(val)
        except ValueError:
            return None
        expr = Document.item_date.isnot(None) & (Document.item_date >= datetime(year, 1, 1)) & (
            Document.item_date < datetime(year + 1, 1, 1)
        )
    elif field == "datein":
        expr = _range_expr(Document.item_date, val)
    elif field == "duein":
        expr = _range_expr(Document.due_date, val)
    elif field == "due":
        if val == "overdue":
            expr = Document.due_date.isnot(None) & (Document.due_date < now())
        elif val == "none":
            expr = Document.due_date.is_(None)
        else:
            expr = _range_expr(Document.due_date, val) if "," in val or ";" in val else Document.due_date.like(f"{val}%")
    elif field == "exist":
        expr = _exist_expr(val, db)
    elif field == "attach.id":
        att_ids = [int(val)] if val.isdigit() else []
        doc_ids = [
            a.document_id
            for a in db.query(DocumentAttachment).filter(DocumentAttachment.id.in_(att_ids or [-1])).all()
        ]
        expr = Document.id.in_(doc_ids or [-1])
    elif field in ("f.id", "fid"):
        try:
            fid = int(val)
        except ValueError:
            return None
        doc_ids = [r.document_id for r in db.query(CustomFieldValue).filter(CustomFieldValue.field_id == fid).all()]
        expr = Document.id.in_(doc_ids or [-1])
    elif field == "f":
        if ":" in val:
            fname, fval = val.split(":", 1)
        elif "=" in val:
            fname, fval = val.split("=", 1)
        else:
            fname, fval = val, "*"
        fld = db.query(CustomField).filter(CustomField.name == fname).first()
        if not fld:
            expr = Document.id.in_([-1])
        elif fval == "*":
            doc_ids = [r.document_id for r in db.query(CustomFieldValue).filter(CustomFieldValue.field_id == fld.id).all()]
            expr = Document.id.in_(doc_ids or [-1])
        else:
            like = fval.replace("*", "%")
            doc_ids = [
                r.document_id
                for r in db.query(CustomFieldValue)
                .filter(CustomFieldValue.field_id == fld.id, CustomFieldValue.value.ilike(like))
                .all()
            ]
            expr = Document.id.in_(doc_ids or [-1])
    elif field.startswith("f:") or field.startswith("f."):
        fname = field.split(":", 1)[-1] if ":" in field else field.split(".", 1)[-1]
        fld = db.query(CustomField).filter(CustomField.name == fname).first()
        if not fld:
            expr = Document.id.in_([-1])
        elif val == "*":
            doc_ids = [r.document_id for r in db.query(CustomFieldValue).filter(CustomFieldValue.field_id == fld.id).all()]
            expr = Document.id.in_(doc_ids or [-1])
        else:
            qv = db.query(CustomFieldValue).filter(CustomFieldValue.field_id == fld.id)
            if op in (">", ">=", "<", "<="):
                try:
                    num = float(val)
                    rows = qv.all()
                    doc_ids = []
                    for r in rows:
                        try:
                            n = float(r.value)
                        except (TypeError, ValueError):
                            continue
                        if (
                            (op == ">" and n > num)
                            or (op == ">=" and n >= num)
                            or (op == "<" and n < num)
                            or (op == "<=" and n <= num)
                        ):
                            doc_ids.append(r.document_id)
                except ValueError:
                    doc_ids = [r.document_id for r in qv.filter(CustomFieldValue.value.ilike(f"%{val}%")).all()]
            else:
                like = val.replace("*", "%")
                doc_ids = [r.document_id for r in qv.filter(CustomFieldValue.value.ilike(like)).all()]
            expr = Document.id.in_(doc_ids or [-1])
    elif field == "field":
        ids = [r.document_id for r in db.query(CustomFieldValue).filter(CustomFieldValue.value.ilike(f"%{val}%")).all()]
        expr = Document.id.in_(ids or [-1])
    else:
        # Unknown field: treat as custom field name or metadata substring
        fld = db.query(CustomField).filter(CustomField.name == field).first()
        if fld:
            ids = [
                r.document_id
                for r in db.query(CustomFieldValue)
                .filter(CustomFieldValue.field_id == fld.id, CustomFieldValue.value.ilike(f"%{val}%"))
                .all()
            ]
            expr = Document.id.in_(ids or [-1])
        else:
            expr = Document.title.ilike(f"%{val}%")
    return expr


def _range_expr(column, val: str):
    parts = [p.strip() for p in val.split(",")]
    if len(parts) == 1 and ";" in parts[0] and not parts[0].lower().startswith("today") and not parts[0].lower().startswith("now"):
        # single date-arithmetic value: treat as lower bound
        start = parse_date_expr(parts[0])
        return column >= start if start else column.like(f"{val}%")
    if len(parts) >= 2:
        start = parse_date_expr(parts[0])
        end = parse_date_expr(parts[1])
        expr = None
        if start:
            expr = column >= start
        if end:
            expr = (expr & (column <= end)) if expr is not None else (column <= end)
        return expr if expr is not None else column.like(f"{val}%")
    start = parse_date_expr(val)
    if start:
        return column >= start
    return column.like(f"{val}%")


def _exist_expr(field: str, db: Session):
    field = field.lower()
    if field in ("tags", "tag"):
        return Document.tags.isnot(None) & (Document.tags != "")
    if field in ("notes", "note"):
        return Document.notes.isnot(None) & (Document.notes != "")
    if field == "due":
        return Document.due_date.isnot(None)
    if field in ("correspondent", "corr"):
        return Document.correspondent_id.isnot(None)
    if field in ("concerning", "conc"):
        return Document.concerning_id.isnot(None)
    if field.startswith("f:") or field.startswith("f."):
        fname = field.split(":", 1)[-1] if ":" in field else field.split(".", 1)[-1]
        fld = db.query(CustomField).filter(CustomField.name == fname).first()
        if not fld:
            return Document.id.in_([-1])
        ids = [r.document_id for r in db.query(CustomFieldValue).filter(CustomFieldValue.field_id == fld.id).all()]
        return Document.id.in_(ids or [-1])
    return Document.id.isnot(None)


def _apply_legacy(query, parsed: ParsedQuery, db: Session):
    """Fallback for empty trees — keep previous key:value behaviour."""
    dummy = Node(kind="and")
    for k, v in parsed.filters.items():
        if k == "tags" and isinstance(v, list):
            for tag in v:
                dummy.children.append(Node(kind="clause", clause=Clause("tags", ":", tag)))
        else:
            dummy.children.append(Node(kind="clause", clause=Clause(k, ":", str(v))))
    expr = _node_to_sql(dummy, db, parsed)
    return query.filter(expr) if expr is not None else query
