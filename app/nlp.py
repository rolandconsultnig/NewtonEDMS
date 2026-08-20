"""Lightweight NLP helpers: dates, language guess, tag/contact suggestions.

This is a portable stand-in for Docspell's Stanford-NLP pipeline. It uses
regular expressions and the tag/contact catalogs rather than a heavy ML model,
so it runs without extra native libraries.
"""
from __future__ import annotations

import re
from datetime import datetime

from sqlalchemy.orm import Session

from app.models import Contact, Equipment, Organization, Tag

_ISO_DATE = re.compile(r"\b(20\d{2}|19\d{2})[-/.](0?[1-9]|1[0-2])[-/.](0?[1-9]|[12]\d|3[01])\b")
_EU_DATE = re.compile(r"\b(0?[1-9]|[12]\d|3[01])[-/.](0?[1-9]|1[0-2])[-/.](20\d{2}|19\d{2})\b")
_WORD = re.compile(r"[A-Za-z][A-Za-z0-9_-]{2,}")


def extract_dates(text: str) -> list[str]:
    if not text:
        return []
    found: list[str] = []
    for match in _ISO_DATE.finditer(text):
        y, m, d = match.group(1), match.group(2).zfill(2), match.group(3).zfill(2)
        found.append(f"{y}-{m}-{d}")
    for match in _EU_DATE.finditer(text):
        d, m, y = match.group(1).zfill(2), match.group(2).zfill(2), match.group(3)
        found.append(f"{y}-{m}-{d}")
    # unique, preserve order
    seen: set[str] = set()
    out: list[str] = []
    for item in found:
        if item not in seen:
            seen.add(item)
            out.append(item)
    return out[:8]


def guess_language(text: str) -> str | None:
    if not text:
        return None
    sample = text[:4000].lower()
    de = sum(sample.count(w) for w in (" und ", " der ", " die ", " das ", " nicht "))
    fr = sum(sample.count(w) for w in (" et ", " les ", " une ", " pour ", " dans "))
    es = sum(sample.count(w) for w in (" que ", " los ", " las ", " para ", " una "))
    en = sum(sample.count(w) for w in (" the ", " and ", " for ", " with ", " this "))
    scores = {"de": de, "fr": fr, "es": es, "en": en}
    best = max(scores, key=scores.get)
    return best if scores[best] >= 2 else "en"


def suggest_tags(db: Session, text: str) -> list[str]:
    if not text:
        return []
    hay = text.lower()
    names = [t.name for t in db.query(Tag).all()]
    hits = [n for n in names if n and re.search(rf"\b{re.escape(n.lower())}\b", hay)]
    return hits[:12]


def suggest_contacts(db: Session, text: str) -> list[Contact]:
    if not text:
        return []
    hay = text.lower()
    contacts = db.query(Contact).all()
    hits = []
    for c in contacts:
        needles = [c.name, c.organization, c.email]
        if any(n and n.lower() in hay for n in needles if n):
            hits.append(c)
    return hits[:12]


def parse_item_date(iso: str) -> datetime | None:
    try:
        return datetime.strptime(iso, "%Y-%m-%d")
    except (TypeError, ValueError):
        return None


def suggest_organizations(db: Session, text: str) -> list[Organization]:
    if not text:
        return []
    hay = text.lower()
    hits = []
    for org in db.query(Organization).all():
        needles = [org.name, *(org.emails or []), *(org.websites or [])]
        if any(n and str(n).lower() in hay for n in needles if n):
            hits.append(org)
    return hits[:12]


def suggest_equipment(db: Session, text: str) -> list[Equipment]:
    if not text:
        return []
    hay = text.lower()
    hits = []
    for eq in db.query(Equipment).all():
        if eq.name and eq.name.lower() in hay:
            hits.append(eq)
    return hits[:12]


def analyze(db: Session, text: str) -> dict:
    dates = extract_dates(text)
    return {
        "tags": suggest_tags(db, text),
        "contacts": suggest_contacts(db, text),
        "organizations": suggest_organizations(db, text),
        "equipment": suggest_equipment(db, text),
        "dates": dates,
        "language": guess_language(text),
        "item_date": parse_item_date(dates[0]) if dates else None,
    }
