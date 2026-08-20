"""Convert office/images/HTML/markdown to PDF, OCR to searchable PDF, thumbnails.

Uses ocrmypdf / tesseract / unoconv / LibreOffice / wkhtmltopdf when installed,
and always has a Python fallback so processing never no-ops.
"""
from __future__ import annotations

import io
import logging
import os
import shutil
import subprocess
import tempfile
from pathlib import Path

from app.config import settings
from app.storage import doc_storage_dir

logger = logging.getLogger("newtonedms.convert")

IMAGE_EXT = {".png", ".jpg", ".jpeg", ".gif", ".bmp", ".tif", ".tiff", ".webp"}
OFFICE_EXT = {".doc", ".docx", ".xls", ".xlsx", ".ppt", ".pptx", ".odt", ".ods", ".odp", ".rtf"}
HTML_EXT = {".html", ".htm"}
MD_EXT = {".md", ".markdown", ".txt"}


def _run(cmd: list[str], timeout: int = 120) -> tuple[bool, str]:
    try:
        p = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout, check=False)
        ok = p.returncode == 0
        return ok, (p.stdout or "") + (p.stderr or "")
    except FileNotFoundError:
        return False, "not installed"
    except Exception as e:
        return False, str(e)


def _cmd_template(kind: str, default: list[str]) -> list[str]:
    raw = getattr(settings, f"cmd_{kind}", "") or ""
    if raw.strip():
        return raw.split()
    return default


def _text_pdf(text: str, dest: Path, title: str = "Document") -> Path:
    from fpdf import FPDF

    pdf = FPDF()
    pdf.set_auto_page_break(auto=True, margin=15)
    pdf.add_page()
    pdf.set_font("Helvetica", size=11)
    pdf.set_title(title)
    for line in (text or "(empty)").splitlines() or [" "]:
        pdf.multi_cell(0, 6, line[:500].encode("latin-1", "replace").decode("latin-1"))
    dest.parent.mkdir(parents=True, exist_ok=True)
    pdf.output(str(dest))
    return dest


def image_to_pdf(src: Path, dest: Path) -> Path:
    from PIL import Image

    dest.parent.mkdir(parents=True, exist_ok=True)
    img = Image.open(src)
    if img.mode not in ("RGB", "L"):
        img = img.convert("RGB")
    buf = io.BytesIO()
    img.save(buf, format="PDF")
    buf.seek(0)
    dest.write_bytes(buf.read())
    return dest


def html_to_pdf(src: Path, dest: Path) -> Path:
    cmd = _cmd_template("wkhtmltopdf", ["wkhtmltopdf", "-s", "A4", str(src), str(dest)])
    ok, _ = _run(cmd, timeout=90)
    if ok and dest.exists() and dest.stat().st_size:
        return dest
    html = src.read_text(encoding="utf-8", errors="ignore")
    text = html
    for tag in ("script", "style"):
        import re

        text = re.sub(rf"<{tag}[\s\S]*?</{tag}>", " ", text, flags=re.I)
    text = re.sub(r"<[^>]+>", " ", text)
    text = re.sub(r"\s+", " ", text)
    return _text_pdf(text, dest, src.stem)


def markdown_to_pdf(src: Path, dest: Path) -> Path:
    raw = src.read_text(encoding="utf-8", errors="ignore")
    try:
        import markdown as md

        html = md.markdown(raw, extensions=["extra", "tables"])
        tmp = dest.with_suffix(".html")
        tmp.write_text(f"<html><body>{html}</body></html>", encoding="utf-8")
        html_to_pdf(tmp, dest)
        tmp.unlink(missing_ok=True)
        return dest
    except Exception:
        return _text_pdf(raw, dest, src.stem)


def office_to_pdf(src: Path, dest: Path) -> Path:
    soffice = shutil.which("soffice") or shutil.which("libreoffice")
    unoconv = shutil.which("unoconv")
    if unoconv:
        cmd = _cmd_template("unoconv", ["unoconv", "-f", "pdf", "-o", str(dest.parent), str(src)])
        ok, _ = _run(cmd, timeout=180)
        produced = dest.parent / (src.stem + ".pdf")
        if ok and produced.exists():
            if produced != dest:
                shutil.copy2(produced, dest)
            return dest
    if soffice:
        with tempfile.TemporaryDirectory() as td:
            cmd = [soffice, "--headless", "--convert-to", "pdf", "--outdir", td, str(src)]
            ok, _ = _run(cmd, timeout=180)
            produced = Path(td) / (src.stem + ".pdf")
            if ok and produced.exists():
                shutil.copy2(produced, dest)
                return dest
    # Fallback: extract text then wrap as PDF
    from app.indexing import _extract_text

    text, _ = _extract_text(src, "")
    return _text_pdf(text or src.name, dest, src.stem)


def decrypt_pdf(src: Path, password: str | None) -> Path:
    from pypdf import PdfReader, PdfWriter

    reader = PdfReader(str(src))
    if reader.is_encrypted:
        if not password:
            raise ValueError("PDF is encrypted; a password is required")
        if reader.decrypt(password) == 0:
            raise ValueError("Wrong PDF password")
    if not reader.is_encrypted:
        return src
    writer = PdfWriter()
    for page in reader.pages:
        writer.add_page(page)
    out = src.with_name(src.stem + ".decrypted.pdf")
    with out.open("wb") as fh:
        writer.write(fh)
    return out


def make_searchable_pdf(src: Path, dest: Path, lang: str = "eng") -> Path:
    dest.parent.mkdir(parents=True, exist_ok=True)
    ocrmypdf = shutil.which("ocrmypdf")
    if ocrmypdf:
        cmd = _cmd_template(
            "ocrmypdf",
            [ocrmypdf, "--skip-text", "-l", lang, "--output-type", "pdfa", str(src), str(dest)],
        )
        ok, msg = _run(cmd, timeout=300)
        if ok and dest.exists():
            return dest
        logger.info("ocrmypdf skipped: %s", msg[:200])
    # Overlay OCR text using a hidden text layer approximation: rebuild pages as images + text PDF
    try:
        import pypdfium2 as pdfium
        from fpdf import FPDF
        from PIL import Image
        import pytesseract

        pdf = pdfium.PdfDocument(str(src))
        try:
            out = FPDF()
            dpi = int(getattr(settings, "preview_dpi", 72) or 72)
            scale = max(dpi / 72.0, 1.0)
            for i in range(len(pdf)):
                page = pdf[i]
                bitmap = page.render(scale=scale)
                pil = bitmap.to_pil()
                text = pytesseract.image_to_string(pil, lang=lang) if shutil.which("tesseract") else ""
                out.add_page()
                tmp = dest.parent / f"_ocr_{i}.jpg"
                pil.convert("RGB").save(tmp, quality=70)
                try:
                    out.image(str(tmp), x=0, y=0, w=210)
                except Exception:
                    pass
                tmp.unlink(missing_ok=True)
                if text.strip():
                    out.set_text_color(255, 255, 255)
                    out.set_font("Helvetica", size=1)
                    out.set_xy(0, 0)
                    out.multi_cell(210, 1, text[:8000].encode("latin-1", "replace").decode("latin-1"))
            dest.parent.mkdir(parents=True, exist_ok=True)
            out.output(str(dest))
            return dest
        finally:
            pdf.close()
    except Exception:
        logger.exception("searchable pdf fallback failed")
        shutil.copy2(src, dest)
        return dest


def first_page_thumbnail(src: Path, dest: Path, dpi: int | None = None) -> Path | None:
    dest.parent.mkdir(parents=True, exist_ok=True)
    dpi = int(dpi or getattr(settings, "preview_dpi", 96) or 96)
    ext = src.suffix.lower()
    try:
        if ext in IMAGE_EXT:
            from PIL import Image

            im = Image.open(src)
            im.thumbnail((dpi * 4, dpi * 5))
            im.convert("RGB").save(dest, "JPEG", quality=80)
            return dest
        if ext != ".pdf":
            pdf = src.with_suffix(".pdf")
            if not pdf.exists():
                return None
            src = pdf
        import pypdfium2 as pdfium

        doc = pdfium.PdfDocument(str(src))
        try:
            if len(doc) == 0:
                return None
            page = doc[0]
            bitmap = page.render(scale=dpi / 72.0)
            bitmap.to_pil().convert("RGB").save(dest, "JPEG", quality=80)
            return dest
        finally:
            doc.close()
    except Exception:
        logger.exception("thumbnail failed for %s", src)
        return None


def to_pdf(src: Path, dest: Path, *, password: str | None = None, lang: str = "eng") -> Path:
    """Convert any supported file to a (preferably searchable) PDF at dest."""
    dest.parent.mkdir(parents=True, exist_ok=True)
    ext = src.suffix.lower()
    work = src
    if ext == ".pdf":
        try:
            work = decrypt_pdf(src, password)
        except ValueError:
            shutil.copy2(src, dest)
            return dest
        return make_searchable_pdf(work, dest, lang=lang)
    if ext in IMAGE_EXT:
        tmp = dest.with_name(dest.stem + ".img.pdf")
        image_to_pdf(src, tmp)
        return make_searchable_pdf(tmp, dest, lang=lang)
    if ext in HTML_EXT:
        html_to_pdf(src, dest)
        return dest
    if ext in MD_EXT:
        markdown_to_pdf(src, dest)
        return dest
    if ext in OFFICE_EXT:
        office_to_pdf(src, dest)
        if dest.exists():
            return make_searchable_pdf(dest, dest, lang=lang)
        return dest
    from app.indexing import _extract_text

    text, _ = _extract_text(src, "")
    return _text_pdf(text or src.name, dest, src.stem)


def pdf_keywords(src: Path) -> list[str]:
    if src.suffix.lower() != ".pdf":
        return []
    try:
        from pypdf import PdfReader

        with src.open("rb") as fh:
            reader = PdfReader(fh)
            if reader.is_encrypted:
                return []
            meta = reader.metadata or {}
            raw = str(meta.get("/Keywords") or meta.get("Keywords") or "")
        parts = [p.strip() for p in raw.replace(";", ",").split(",") if p.strip()]
        return parts[:32]
    except Exception:
        return []


def merge_pdfs(paths: list[Path], dest: Path) -> Path:
    from pypdf import PdfReader, PdfWriter

    writer = PdfWriter()
    dest.parent.mkdir(parents=True, exist_ok=True)
    for p in paths:
        if not p.exists():
            continue
        pdf = p if p.suffix.lower() == ".pdf" else to_pdf(p, p.with_suffix(".pdf"))
        try:
            reader = PdfReader(str(pdf))
            if reader.is_encrypted:
                continue
            for page in reader.pages:
                writer.add_page(page)
        except Exception:
            logger.warning("skip merge page %s", p)
    with dest.open("wb") as fh:
        writer.write(fh)
    return dest
