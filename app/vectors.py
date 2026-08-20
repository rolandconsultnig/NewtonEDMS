"""Hashing-trick embeddings, cosine vector search, and extractive RAG."""
from __future__ import annotations

import hashlib
import json
import math
import re
from pathlib import Path

DIM = 256
_SENT = re.compile(r"(?<=[.!?])\s+")
_WORD = re.compile(r"[A-Za-z][A-Za-z0-9_-]{2,}")


def embed(text: str, dim: int = DIM) -> list[float]:
    vec = [0.0] * dim
    for w in _WORD.finditer((text or "").lower()):
        h = int(hashlib.md5(w.group(0).encode()).hexdigest(), 16)
        vec[h % dim] += 1.0 if (h >> 8) & 1 == 0 else -1.0
    n = math.sqrt(sum(x * x for x in vec)) or 1.0
    return [x / n for x in vec]


def cosine(a: list[float], b: list[float]) -> float:
    n = min(len(a), len(b))
    return sum(a[i] * b[i] for i in range(n))


def chunk_text(text: str, size: int = 800) -> list[str]:
    text = (text or "").strip()
    if not text:
        return []
    sents = _SENT.split(text) or [text]
    chunks, buf = [], ""
    for s in sents:
        if len(buf) + len(s) > size and buf:
            chunks.append(buf.strip())
            buf = s
        else:
            buf = (buf + " " + s).strip()
    if buf:
        chunks.append(buf)
    return chunks[:40]


def index_document(db, doc_id: int, title: str, text: str) -> int:
    from app.models import VectorChunk

    db.query(VectorChunk).filter(VectorChunk.document_id == doc_id).delete()
    n = 0
    for i, chunk in enumerate(chunk_text((title or "") + "\n" + (text or ""))):
        db.add(
            VectorChunk(
                document_id=doc_id,
                ordinal=i,
                text=chunk[:4000],
                vector=embed(chunk),
            )
        )
        n += 1
    db.commit()
    return n


def search(db, query: str, limit: int = 8, document_ids: list[int] | None = None) -> list[dict]:
    from app.models import VectorChunk

    qv = embed(query)
    q = db.query(VectorChunk)
    if document_ids:
        q = q.filter(VectorChunk.document_id.in_(document_ids))
    scored = []
    for row in q.limit(5000).all():
        vec = row.vector or []
        if not vec:
            continue
        scored.append((cosine(qv, vec), row))
    scored.sort(key=lambda x: -x[0])
    out = []
    for score, row in scored[:limit]:
        out.append(
            {
                "document_id": row.document_id,
                "ordinal": row.ordinal,
                "text": row.text,
                "score": round(float(score), 4),
            }
        )
    return out


def answer(db, query: str, limit: int = 6) -> dict:
    hits = search(db, query, limit=limit)
    q_terms = {w.group(0).lower() for w in _WORD.finditer(query)}
    best = ""
    best_n = 0
    for h in hits:
        for sent in _SENT.split(h["text"]):
            n = sum(1 for t in q_terms if t in sent.lower())
            if n > best_n:
                best_n = n
                best = sent.strip()
    context = "\n---\n".join(h["text"] for h in hits)
    backend = "hashing"
    llm_answer = _llm_answer(query, context)
    if llm_answer:
        best = llm_answer
        backend = "llm"
    return {
        "query": query,
        "answer": best or (hits[0]["text"][:400] if hits else ""),
        "hits": hits,
        "context": context[:8000],
        "backend": backend,
    }


def _llm_answer(query: str, context: str) -> str | None:
    from app.config import settings

    url = (getattr(settings, "llm_url", "") or "").rstrip("/")
    if not url:
        return None
    try:
        import httpx

        model = getattr(settings, "llm_model", "") or "llama"
        headers = {"Content-Type": "application/json"}
        key = getattr(settings, "llm_api_key", "") or ""
        if key:
            headers["Authorization"] = f"Bearer {key}"
        prompt = (
            "Answer using only the document excerpts. If unsure, say you do not know.\n\n"
            f"Excerpts:\n{context[:6000]}\n\nQuestion: {query}\nAnswer:"
        )
        payload = {
            "model": model,
            "messages": [
                {"role": "system", "content": "You are NewtonEDMS retrieval assistant."},
                {"role": "user", "content": prompt},
            ],
            "max_tokens": 400,
            "temperature": 0.1,
        }
        chat_url = url if url.endswith("/chat/completions") else url + "/v1/chat/completions"
        r = httpx.post(chat_url, json=payload, headers=headers, timeout=30)
        if r.status_code >= 400:
            r = httpx.post(url, json={"prompt": prompt, "query": query, "context": context[:6000]}, headers=headers, timeout=30)
        r.raise_for_status()
        data = r.json()
        if isinstance(data, dict):
            choices = data.get("choices") or []
            if choices:
                msg = choices[0].get("message") or {}
                return (msg.get("content") or choices[0].get("text") or "").strip() or None
            return (data.get("answer") or data.get("text") or "").strip() or None
    except Exception:
        return None
    return None
