"""Multinomial Naive Bayes tag classifier trained on confirmed documents.

Categories can be whitelisted or blacklisted so workflow tags (todo/done)
are not learned from text.
"""
from __future__ import annotations

import json
import math
import re
from collections import Counter, defaultdict
from pathlib import Path

from app import database
from app.models import Document, Tag

_WORD = re.compile(r"[A-Za-z][A-Za-z0-9_-]{2,}")
MODEL_NAME = "classifier.json"


def _model_path() -> Path:
    p = database.STORAGE_DIR / MODEL_NAME
    p.parent.mkdir(parents=True, exist_ok=True)
    return p


def tokenize(text: str) -> list[str]:
    return [w.group(0).lower() for w in _WORD.finditer(text or "")]


def _allowed_tags(db, whitelist: list[str], blacklist: list[str]) -> set[str]:
    rows = db.query(Tag).all()
    allowed = set()
    for t in rows:
        cat = (t.category or "").strip().lower()
        if whitelist:
            if cat in {c.lower() for c in whitelist}:
                allowed.add(t.name.lower())
        elif blacklist:
            if cat not in {c.lower() for c in blacklist}:
                allowed.add(t.name.lower())
        else:
            allowed.add(t.name.lower())
    return allowed


def train(db, whitelist: list[str] | None = None, blacklist: list[str] | None = None) -> dict:
    allowed = _allowed_tags(db, whitelist or [], blacklist or [])
    docs = (
        db.query(Document)
        .filter(Document.deleted_at.is_(None), Document.extracted_text.isnot(None))
        .all()
    )
    class_docs: dict[str, int] = Counter()
    class_tf: dict[str, Counter] = defaultdict(Counter)
    vocab: set[str] = set()
    n_docs = 0
    for d in docs:
        tags = [t.strip().lower() for t in (d.tags or "").split(",") if t.strip()]
        tags = [t for t in tags if t in allowed]
        if not tags:
            continue
        tokens = tokenize((d.extracted_text or "") + " " + (d.title or ""))
        if not tokens:
            continue
        n_docs += 1
        for tag in tags:
            class_docs[tag] += 1
            class_tf[tag].update(tokens)
            vocab.update(tokens)
    model = {
        "n_docs": n_docs,
        "vocab": sorted(vocab)[:50_000],
        "class_docs": dict(class_docs),
        "class_tf": {k: dict(v.most_common(8000)) for k, v in class_tf.items()},
        "whitelist": whitelist or [],
        "blacklist": blacklist or [],
    }
    _model_path().write_text(json.dumps(model), encoding="utf-8")
    return {"docs": n_docs, "classes": len(class_docs), "vocab": len(vocab)}


def load_model() -> dict | None:
    p = _model_path()
    if not p.exists():
        return None
    try:
        return json.loads(p.read_text(encoding="utf-8"))
    except Exception:
        return None


def predict(text: str, top_k: int = 5) -> list[tuple[str, float]]:
    model = load_model()
    if not model or not model.get("class_docs"):
        return []
    tokens = tokenize(text)
    if not tokens:
        return []
    vocab_n = max(len(model.get("vocab") or []), 1)
    n_docs = max(int(model.get("n_docs") or 1), 1)
    scores: list[tuple[str, float]] = []
    tf_query = Counter(tokens)
    for label, n_c in model["class_docs"].items():
        logp = math.log((n_c + 1) / (n_docs + 2))
        ctf = model["class_tf"].get(label) or {}
        total = sum(ctf.values()) + vocab_n
        for w, c in tf_query.items():
            logp += c * math.log((ctf.get(w, 0) + 1) / total)
        scores.append((label, logp))
    scores.sort(key=lambda x: -x[1])
    if not scores:
        return []
    m = scores[0][1]
    exp = [(lab, math.exp(s - m)) for lab, s in scores[:top_k]]
    z = sum(p for _, p in exp) or 1.0
    return [(lab, round(p / z, 4)) for lab, p in exp]
