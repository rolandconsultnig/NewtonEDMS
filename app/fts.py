"""Full-text search backends: Whoosh (default), SQLite FTS5, PostgreSQL, Solr."""
from __future__ import annotations

import logging
from urllib.parse import urljoin

from app import database
from app.config import settings

logger = logging.getLogger("newtonedms.fts")


def _backend() -> str:
    chosen = (settings.fts_backend or "auto").lower()
    if chosen != "auto":
        return chosen
    if settings.solr_url:
        return "solr"
    url = (settings.database_url or "").lower()
    if url.startswith("postgres"):
        return "postgres"
    return "whoosh"


def index_text(doc_id: int, title: str, tags: str, content: str) -> None:
    kind = _backend()
    try:
        if kind == "solr":
            _solr_index(doc_id, title, tags, content)
        elif kind == "postgres":
            _pg_index(doc_id, title, tags, content)
        elif kind == "sqlite":
            _sqlite_index(doc_id, title, tags, content)
        else:
            from app.indexing import index_document

            index_document(doc_id, title, tags, "", 0, content_override=content)
            return
        # Always keep Whoosh as a fallback index too unless Solr is exclusive.
        if kind != "whoosh":
            from app.indexing import index_document

            index_document(doc_id, title, tags, "", 0, content_override=content)
    except Exception:
        logger.exception("fts index failed for %s (%s)", doc_id, kind)


def search(query: str, limit: int = 100) -> list[tuple[int, float]]:
    """Return ``(doc_id, score)`` pairs, highest score first."""
    if not (query or "").strip():
        return []
    kind = _backend()
    try:
        if kind == "solr":
            return _solr_search(query, limit)
        if kind == "postgres":
            return _pg_search(query, limit)
        if kind == "sqlite":
            return _sqlite_search(query, limit)
    except Exception:
        logger.exception("fts search via %s failed; falling back to Whoosh", kind)
    from app.indexing import search_documents

    ids = search_documents(query, limit=limit)
    n = max(len(ids), 1)
    return [(i, float(n - idx) / n) for idx, i in enumerate(ids)]


def highlight(text: str, query: str, radius: int = 60) -> list[str]:
    """Return snippets of ``text`` with matching terms wrapped in ``<mark>``."""
    if not text or not query:
        return []
    import re

    terms = [t for t in re.split(r"\s+", query.strip()) if t and t[0].isalnum()]
    if not terms:
        return []
    pattern = re.compile("|".join(re.escape(t) for t in terms), re.I)
    snippets: list[str] = []
    for match in pattern.finditer(text):
        start = max(0, match.start() - radius)
        end = min(len(text), match.end() + radius)
        chunk = text[start:end]
        marked = pattern.sub(lambda m: f"<mark>{m.group(0)}</mark>", chunk)
        if start:
            marked = "…" + marked
        if end < len(text):
            marked = marked + "…"
        snippets.append(marked)
        if len(snippets) >= 5:
            break
    return snippets


def _solr_index(doc_id: int, title: str, tags: str, content: str) -> None:
    import httpx

    url = urljoin(settings.solr_url.rstrip("/") + "/", "update/json/docs")
    httpx.post(
        url,
        json={"id": str(doc_id), "title": title or "", "tags": tags or "", "content": content or ""},
        params={"commit": "true"},
        timeout=8.0,
    ).raise_for_status()


def _solr_search(query: str, limit: int) -> list[tuple[int, float]]:
    import httpx

    url = urljoin(settings.solr_url.rstrip("/") + "/", "select")
    r = httpx.get(
        url,
        params={"q": query, "df": "content", "rows": limit, "fl": "id,score", "wt": "json"},
        timeout=8.0,
    )
    r.raise_for_status()
    docs = (r.json().get("response") or {}).get("docs") or []
    out = []
    for d in docs:
        try:
            out.append((int(d["id"]), float(d.get("score") or 0)))
        except (TypeError, ValueError, KeyError):
            continue
    return out


def _pg_index(doc_id: int, title: str, tags: str, content: str) -> None:
    from sqlalchemy import text

    blob = " ".join(filter(None, [title, tags, content]))
    with database.engine.begin() as conn:
        conn.execute(
            text(
                "UPDATE documents SET extracted_text = COALESCE(extracted_text, :blob) "
                "WHERE id = :id"
            ),
            {"blob": blob[:500_000], "id": doc_id},
        )
        try:
            conn.execute(
                text(
                    "UPDATE documents SET fts = to_tsvector('english', "
                    "coalesce(title,'') || ' ' || coalesce(tags,'') || ' ' || coalesce(extracted_text,'')) "
                    "WHERE id = :id"
                ),
                {"id": doc_id},
            )
        except Exception:
            pass


def _pg_search(query: str, limit: int) -> list[tuple[int, float]]:
    from sqlalchemy import text

    with database.engine.begin() as conn:
        try:
            rows = conn.execute(
                text(
                    "SELECT id, ts_rank(fts, plainto_tsquery('english', :q)) AS score "
                    "FROM documents WHERE fts @@ plainto_tsquery('english', :q) "
                    "ORDER BY score DESC LIMIT :lim"
                ),
                {"q": query, "lim": limit},
            ).fetchall()
            return [(int(r[0]), float(r[1] or 0)) for r in rows]
        except Exception:
            rows = conn.execute(
                text(
                    "SELECT id FROM documents WHERE extracted_text ILIKE :q "
                    "OR title ILIKE :q LIMIT :lim"
                ),
                {"q": f"%{query}%", "lim": limit},
            ).fetchall()
            n = max(len(rows), 1)
            return [(int(r[0]), float(n - i) / n) for i, r in enumerate(rows)]


def _sqlite_ensure(conn) -> None:
    conn.exec_driver_sql(
        "CREATE VIRTUAL TABLE IF NOT EXISTS doc_fts USING fts5("
        "doc_id UNINDEXED, title, tags, content, tokenize='porter')"
    )


def _sqlite_index(doc_id: int, title: str, tags: str, content: str) -> None:
    with database.engine.begin() as conn:
        _sqlite_ensure(conn)
        conn.exec_driver_sql("DELETE FROM doc_fts WHERE doc_id = ?", (str(doc_id),))
        conn.exec_driver_sql(
            "INSERT INTO doc_fts(doc_id, title, tags, content) VALUES (?, ?, ?, ?)",
            (str(doc_id), title or "", tags or "", content or ""),
        )


def _sqlite_search(query: str, limit: int) -> list[tuple[int, float]]:
    with database.engine.begin() as conn:
        _sqlite_ensure(conn)
        rows = conn.exec_driver_sql(
            "SELECT doc_id, rank FROM doc_fts WHERE doc_fts MATCH ? ORDER BY rank LIMIT ?",
            (query, limit),
        ).fetchall()
        out = []
        for r in rows:
            try:
                out.append((int(r[0]), float(r[1] or 0)))
            except (TypeError, ValueError):
                continue
        return out
