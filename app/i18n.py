"""GUI translation catalogs served to the SPA."""
from __future__ import annotations

import json
from functools import lru_cache
from pathlib import Path

from app.database import FRONTEND_DIR

I18N_DIR = FRONTEND_DIR / "i18n"
SUPPORTED = ("en", "de", "fr", "es")


@lru_cache(maxsize=8)
def load_catalog(locale: str) -> dict:
    loc = (locale or "en").split("-")[0].lower()
    if loc not in SUPPORTED:
        loc = "en"
    path = I18N_DIR / f"{loc}.json"
    if not path.exists():
        path = I18N_DIR / "en.json"
    if not path.exists():
        return {}
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return {}


def t(locale: str, key: str, **kwargs) -> str:
    cat = load_catalog(locale)
    text = cat.get(key) or load_catalog("en").get(key) or key
    try:
        return text.format(**kwargs)
    except Exception:
        return text
