"""Detect which conversion / OCR binaries are on PATH."""
from __future__ import annotations

import shutil

from app.config import settings


def _which(cmd: str) -> str | None:
    name = (cmd or "").split()[0] if cmd else ""
    if not name:
        return None
    return shutil.which(name)


def installed_tools() -> list[dict]:
    specs = [
        ("tesseract", "OCR (Tesseract)", settings.cmd_tesseract or "tesseract"),
        ("ocrmypdf", "Searchable PDF (ocrmypdf)", settings.cmd_ocrmypdf or "ocrmypdf"),
        ("unoconv", "Office via unoconv", settings.cmd_unoconv or "unoconv"),
        ("libreoffice", "LibreOffice / soffice", "soffice"),
        ("soffice", "LibreOffice binary", "libreoffice"),
        ("wkhtmltopdf", "HTML to PDF", settings.cmd_wkhtmltopdf or "wkhtmltopdf"),
        ("pdftotext", "Poppler pdftotext", "pdftotext"),
    ]
    seen: set[str] = set()
    out: list[dict] = []
    for tid, name, cmd in specs:
        path = _which(cmd)
        key = tid if tid != "soffice" else "libreoffice"
        if key in seen:
            if path:
                for row in out:
                    if row["id"] == "libreoffice" and path:
                        row["available"] = True
                        row["path"] = row["path"] or path
            continue
        seen.add(key)
        out.append({"id": key, "name": name, "available": bool(path), "path": path or "", "command": cmd})
    # Python fallbacks always present
    out.append({"id": "pdf", "name": "PDF preview / split (pypdf)", "available": True, "path": "", "command": ""})
    out.append({"id": "pillow", "name": "Image conversion (Pillow)", "available": True, "path": "", "command": ""})
    try:
        import pytesseract  # noqa: F401

        tess = next((r for r in out if r["id"] == "tesseract"), None)
        if tess and not tess["available"]:
            tess["available"] = True
            tess["path"] = tess["path"] or "pytesseract"
    except Exception:
        pass
    return out
