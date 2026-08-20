"""Zonal / machine-learning intelligent document processing.

Zones are rectangles on a page. Text is cropped with pdfplumber (or OCR on a
rendered tile) and classified into field types with a hashed-feature model
trained from confirmed custom-field values.
"""
from __future__ import annotations

import json
import math
import re
from collections import Counter, defaultdict
from pathlib import Path

from app import database
from app.models import CustomField, CustomFieldValue, Document

_WORD = re.compile(r"[A-Za-z0-9][A-Za-z0-9._/-]{1,}")
MODEL = "idp_model.json"

FIELD_PATTERNS = {
    "invoice_no": re.compile(r"\b(INV[-/]?\d{3,}|invoice\s*#?\s*\d+)\b", re.I),
    "iban": re.compile(r"\b[A-Z]{2}\d{2}[A-Z0-9]{10,30}\b"),
    "amount": re.compile(r"(?:EUR|USD|GBP|NGN|€|\$)\s?\d{1,3}(?:[.,]\d{3})*(?:[.,]\d{2})|\b\d+[.,]\d{2}\b"),
    "date": re.compile(r"\b(?:20\d{2}|19\d{2})[-/.](0?[1-9]|1[0-2])[-/.](0?[1-9]|[12]\d|3[01])\b"),
    "email": re.compile(r"\b[\w.+-]+@[\w-]+\.[\w.-]+\b"),
    "vat": re.compile(r"\b[A-Z]{2}\d{8,12}\b"),
}


def _model_path() -> Path:
    p = database.STORAGE_DIR / MODEL
    p.parent.mkdir(parents=True, exist_ok=True)
    return p


def extract_zone(pdf_path: Path, page: int, x: float, y: float, w: float, h: float) -> str:
    try:
        import pdfplumber

        with pdfplumber.open(str(pdf_path)) as pdf:
            if page < 1 or page > len(pdf.pages):
                return ""
            cropped = pdf.pages[page - 1].crop((x, y, x + w, y + h))
            return (cropped.extract_text() or "").strip()
    except Exception:
        pass
    try:
        import pypdfium2 as pdfium
        import pytesseract
        from PIL import Image

        doc = pdfium.PdfDocument(str(pdf_path))
        try:
            pg = doc[page - 1]
            bitmap = pg.render(scale=2)
            im = bitmap.to_pil()
            # PDF points → pixels at 2x (144 dpi-ish)
            scale = 2 * 72 / 72
            box = (int(x * scale), int(y * scale), int((x + w) * scale), int((y + h) * scale))
            tile = im.crop(box)
            return pytesseract.image_to_string(tile).strip()
        finally:
            doc.close()
    except Exception:
        return ""


def classify_value(text: str) -> list[tuple[str, float]]:
    hits = []
    for name, pat in FIELD_PATTERNS.items():
        if pat.search(text or ""):
            hits.append((name, 0.9))
    model = _load()
    if model and text:
        tokens = [w.group(0).lower() for w in _WORD.finditer(text)]
        scores = []
        for label, tf in model.get("class_tf", {}).items():
            n = sum(tf.values()) + 1
            logp = math.log((model["class_docs"].get(label, 1) + 1) / (model.get("n_docs", 1) + 2))
            for t in tokens:
                logp += math.log((tf.get(t, 0) + 1) / n)
            scores.append((label, logp))
        scores.sort(key=lambda x: -x[1])
        if scores:
            m = scores[0][1]
            exp = [(lab, math.exp(s - m)) for lab, s in scores[:5]]
            z = sum(p for _, p in exp) or 1
            hits.extend((lab, round(p / z, 4)) for lab, p in exp)
    seen = set()
    out = []
    for lab, sc in hits:
        if lab not in seen:
            seen.add(lab)
            out.append((lab, sc))
    return out[:6]


def apply_zones(db, doc: Document, zones: list[dict], pdf_path: Path) -> dict:
    captured: dict[str, str] = {}
    for z in zones:
        text = extract_zone(
            pdf_path,
            int(z.get("page") or 1),
            float(z.get("x") or 0),
            float(z.get("y") or 0),
            float(z.get("w") or 100),
            float(z.get("h") or 24),
        )
        name = z.get("name") or z.get("field") or "zone"
        if text:
            captured[name] = text
            guesses = classify_value(text)
            if guesses and not z.get("name"):
                captured[guesses[0][0]] = text
    meta = dict(doc.metadata_json or {})
    meta["idp"] = captured
    doc.metadata_json = meta
    for name, value in captured.items():
        fld = db.query(CustomField).filter(CustomField.name == name).first()
        if fld:
            existing = (
                db.query(CustomFieldValue)
                .filter(CustomFieldValue.field_id == fld.id, CustomFieldValue.document_id == doc.id)
                .first()
            )
            if existing:
                existing.value = value
            else:
                db.add(CustomFieldValue(field_id=fld.id, document_id=doc.id, value=value))
    db.commit()
    return captured


def train(db) -> dict:
    class_docs: Counter = Counter()
    class_tf: dict[str, Counter] = defaultdict(Counter)
    n = 0
    for row in db.query(CustomFieldValue).all():
        fld = db.get(CustomField, row.field_id)
        if not fld or not row.value:
            continue
        tokens = [w.group(0).lower() for w in _WORD.finditer(row.value)]
        if not tokens:
            continue
        n += 1
        class_docs[fld.name] += 1
        class_tf[fld.name].update(tokens)
    model = {
        "n_docs": n,
        "class_docs": dict(class_docs),
        "class_tf": {k: dict(v) for k, v in class_tf.items()},
    }
    _model_path().write_text(json.dumps(model), encoding="utf-8")
    return {"docs": n, "classes": len(class_docs)}


def auto_capture(db, doc: Document, pdf_path: Path | None) -> dict:
    """Run regex IDP over extracted text plus any stored zone template."""
    text = doc.extracted_text or ""
    if not text:
        text = " ".join(filter(None, [doc.title, doc.name, doc.notes]))
        if pdf_path and pdf_path.exists() and pdf_path.suffix.lower() in {".txt", ".md", ".csv"}:
            try:
                text += " " + pdf_path.read_text(encoding="utf-8", errors="ignore")
            except Exception:
                pass
    captured = {}
    for name, pat in FIELD_PATTERNS.items():
        m = pat.search(text)
        if m:
            captured[name] = m.group(0)
    zones = (doc.metadata_json or {}).get("zones") or []
    if zones and pdf_path and pdf_path.exists():
        captured.update(apply_zones(db, doc, zones, pdf_path))
    meta = dict(doc.metadata_json or {})
    meta.setdefault("idp", {}).update(captured)
    doc.metadata_json = meta
    db.commit()
    return captured


def _load() -> dict | None:
    p = _model_path()
    if not p.exists():
        return None
    try:
        return json.loads(p.read_text(encoding="utf-8"))
    except Exception:
        return None
