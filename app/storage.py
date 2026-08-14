"""File-storage helpers (path safety, size/extension policy)."""

from pathlib import Path

from fastapi import HTTPException, status

from app import database
from app.config import settings


def safe_filename(name: str) -> str:
    return Path(name).name.replace("..", "").replace("/", "_").replace("\\", "_") or "file"


def doc_storage_dir(doc_id: int) -> Path:
    # Access STORAGE_DIR via the database module so tests can monkeypatch it.
    d = database.STORAGE_DIR / f"doc_{doc_id}"
    d.mkdir(parents=True, exist_ok=True)
    return d


def validate_upload_filename(name: str) -> None:
    ext = Path(name).suffix.lower().lstrip(".")
    blocked = {e.strip().lower() for e in settings.blocked_extensions.split(",") if e.strip()}
    if ext and ext in blocked:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"File type '.{ext}' is not allowed",
        )


def save_upload(file_obj, dest: Path) -> int:
    """Stream ``file_obj`` to ``dest`` while enforcing the configured size cap.

    Returns the number of bytes written and removes the partial file if the
    upload exceeds ``settings.max_upload_bytes``.
    """
    written = 0
    chunk_size = 1024 * 1024
    with dest.open("wb") as out:
        while True:
            chunk = file_obj.read(chunk_size)
            if not chunk:
                break
            written += len(chunk)
            if written > settings.max_upload_bytes:
                out.close()
                dest.unlink(missing_ok=True)
                raise HTTPException(
                    status_code=status.HTTP_413_REQUEST_ENTITY_TOO_LARGE,
                    detail=f"File exceeds the {settings.max_upload_bytes} byte limit",
                )
            out.write(chunk)
    return written
