"""Archive and email extraction with nested zip-in-zip and eml-in-zip.

Relative paths inside archives are preserved (no flattening to basename).
"""
from __future__ import annotations

import email
import fnmatch
import mimetypes
import zipfile
from email import policy
from pathlib import Path

from app.config import settings
from app.storage import safe_filename, validate_upload_filename

MAX_NEST = 6


def _safe_relpath(name: str, dest_dir: Path) -> Path | None:
    rel = Path(name.replace("\\", "/"))
    if rel.is_absolute() or any(p in ("..", "") for p in rel.parts):
        parts = [safe_filename(p) for p in rel.parts if p not in ("", ".", "..")]
        if not parts:
            return None
        rel = Path(*parts)
    else:
        parts = [safe_filename(p) for p in rel.parts]
        if not parts:
            return None
        rel = Path(*parts)
    target = (dest_dir / rel).resolve()
    try:
        target.relative_to(dest_dir.resolve())
    except ValueError:
        return None
    return target


def extract_zip(archive: Path, dest_dir: Path) -> list[Path]:
    """Extract a zip into ``dest_dir``, honouring the upload size budget."""
    dest_dir.mkdir(parents=True, exist_ok=True)
    written: list[Path] = []
    budget = settings.max_extract_bytes
    try:
        with zipfile.ZipFile(archive) as zf:
            for info in zf.infolist():
                if info.is_dir() or info.file_size <= 0:
                    continue
                target = _safe_relpath(info.filename, dest_dir)
                if target is None:
                    continue
                try:
                    validate_upload_filename(target.name)
                except Exception:
                    continue
                if info.file_size > budget:
                    continue
                target.parent.mkdir(parents=True, exist_ok=True)
                with zf.open(info) as src, target.open("wb") as out:
                    data = src.read(min(info.file_size, budget))
                    out.write(data)
                    budget -= len(data)
                written.append(target)
                if budget <= 0:
                    break
    except zipfile.BadZipFile:
        return []
    return written


def extract_eml(eml_path: Path, dest_dir: Path) -> tuple[str, list[Path]]:
    """Return (subject + body text, attachment paths)."""
    dest_dir.mkdir(parents=True, exist_ok=True)
    try:
        with eml_path.open("rb") as fh:
            msg = email.message_from_binary_file(fh, policy=policy.default)
    except Exception:
        return "", []
    subject = str(msg.get("Subject") or "")
    from_ = str(msg.get("From") or "")
    date = str(msg.get("Date") or "")
    bodies: list[str] = [f"Subject: {subject}", f"From: {from_}", f"Date: {date}"]
    attachments: list[Path] = []
    budget = settings.max_extract_bytes
    for part in msg.walk():
        if part.get_content_maintype() == "multipart":
            continue
        filename = part.get_filename()
        payload = part.get_payload(decode=True) or b""
        ctype = part.get_content_type()
        if filename:
            name = safe_filename(filename)
            try:
                validate_upload_filename(name)
            except Exception:
                continue
            if len(payload) > budget:
                continue
            target = dest_dir / name
            target.write_bytes(payload)
            attachments.append(target)
            budget -= len(payload)
        elif ctype.startswith("text/") and payload:
            try:
                bodies.append(payload.decode(part.get_content_charset() or "utf-8", errors="ignore"))
            except Exception:
                pass
    return "\n".join(bodies), attachments


def extract_nested(path: Path, dest_dir: Path, *, depth: int = 0, max_depth: int = MAX_NEST) -> tuple[str, list[Path]]:
    """Recursively extract zip and eml, returning (extra text, all files)."""
    dest_dir.mkdir(parents=True, exist_ok=True)
    extra = ""
    files: list[Path] = []
    ext = path.suffix.lower()
    if ext == ".zip":
        files = extract_zip(path, dest_dir)
    elif ext in (".eml", ".msg"):
        body, files = extract_eml(path, dest_dir)
        extra += "\n" + body
    else:
        return extra, files
    if depth >= max_depth:
        return extra, files
    nested: list[Path] = []
    for f in files:
        child_ext = f.suffix.lower()
        if child_ext in {".zip", ".eml", ".msg"}:
            child_dir = dest_dir / f"_nested_{depth}_{safe_filename(f.stem)}"
            more_text, more_files = extract_nested(f, child_dir, depth=depth + 1, max_depth=max_depth)
            extra += "\n" + more_text
            nested.extend(more_files)
    return extra, files + nested


def matches_glob(name: str, pattern: str) -> bool:
    if not pattern or pattern == "*":
        return True
    return any(fnmatch.fnmatch(name.lower(), p.strip().lower()) for p in pattern.split(",") if p.strip())


def guess_mime(path: Path) -> str:
    return mimetypes.guess_type(path.name)[0] or "application/octet-stream"
