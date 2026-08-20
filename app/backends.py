"""File backends: filesystem, database blobs, and S3."""
from __future__ import annotations

import logging
import tempfile
from pathlib import Path

from app import database
from app.config import settings
from app.models import FileBlob, StorageStore

logger = logging.getLogger("newtonedms.backends")

FS_PREFIX = "fs:"
DB_PREFIX = "dbblob:"
S3_PREFIX = "s3:"
AZURE_PREFIX = "azure:"
SMB_PREFIX = "smb:"


def _default_store(db) -> StorageStore | None:
    return (
        db.query(StorageStore)
        .filter(StorageStore.is_default.is_(True))
        .first()
        or db.query(StorageStore).first()
    )


def persist(db, key: str, path: Path, mime: str | None = None) -> str:
    """Store ``path`` according to the default backend; return a locator string."""
    store = _default_store(db)
    kind = (store.kind if store else "fs") or "fs"
    kind = kind.lower()
    if kind == "db":
        data = path.read_bytes()
        existing = db.query(FileBlob).filter(FileBlob.key == key).first()
        if existing:
            existing.content = data
            existing.size = len(data)
            existing.mime = mime
            db.commit()
            return f"{DB_PREFIX}{existing.id}"
        blob = FileBlob(key=key, content=data, size=len(data), mime=mime)
        db.add(blob)
        db.commit()
        db.refresh(blob)
        return f"{DB_PREFIX}{blob.id}"
    if kind == "s3":
        cfg = dict((store.config if store else None) or {})
        bucket = cfg.get("bucket") or settings.s3_bucket
        if not bucket:
            return str(path)
        import boto3

        client = boto3.client(
            "s3",
            endpoint_url=cfg.get("endpoint") or settings.s3_endpoint or None,
            aws_access_key_id=cfg.get("access_key") or settings.s3_access_key or None,
            aws_secret_access_key=cfg.get("secret_key") or settings.s3_secret_key or None,
            region_name=cfg.get("region") or settings.s3_region,
        )
        s3_key = f"{key}/{path.name}"
        client.upload_file(str(path), bucket, s3_key)
        return f"{S3_PREFIX}{bucket}/{s3_key}"
    if kind in ("azure", "blob"):
        from app.connectors import azure_upload

        cfg = dict((store.config if store else None) or {})
        loc = azure_upload(path, f"{key}/{path.name}", cfg)
        return loc
    if kind == "smb":
        from app.connectors import smb_fetch
        from pathlib import Path as _P

        cfg = dict((store.config if store else None) or {})
        remote = cfg.get("remote") or cfg.get("path") or ""
        if remote:
            smb_fetch(cfg, remote.rstrip("/\\") + "/" + path.name, path)
        return f"{SMB_PREFIX}{path}"
    return str(path)


def resolve(locator: str) -> Path:
    """Return a local path for ``locator``, downloading when needed."""
    if not locator:
        raise FileNotFoundError("empty locator")
    if locator.startswith(DB_PREFIX):
        blob_id = int(locator[len(DB_PREFIX) :])
        db = database.SessionLocal()
        try:
            blob = db.get(FileBlob, blob_id)
            if not blob:
                raise FileNotFoundError(locator)
            tmp = Path(tempfile.gettempdir()) / f"newton_blob_{blob_id}"
            tmp.write_bytes(blob.content)
            return tmp
        finally:
            db.close()
    if locator.startswith(S3_PREFIX):
        rest = locator[len(S3_PREFIX) :]
        bucket, _, key = rest.partition("/")
        import boto3

        client = boto3.client(
            "s3",
            endpoint_url=settings.s3_endpoint or None,
            aws_access_key_id=settings.s3_access_key or None,
            aws_secret_access_key=settings.s3_secret_key or None,
            region_name=settings.s3_region,
        )
        tmp = Path(tempfile.gettempdir()) / f"newton_s3_{Path(key).name}"
        client.download_file(bucket, key, str(tmp))
        return tmp
    if locator.startswith(AZURE_PREFIX):
        from app.connectors import azure_download

        cfg = {}
        db = database.SessionLocal()
        try:
            store = _default_store(db)
            cfg = dict((store.config if store else None) or {})
        finally:
            db.close()
        return azure_download(locator, cfg)
    if locator.startswith(SMB_PREFIX):
        p = Path(locator[len(SMB_PREFIX) :])
        if p.exists():
            return p
        raise FileNotFoundError(locator)
    if locator.startswith(FS_PREFIX):
        locator = locator[len(FS_PREFIX) :]
    p = Path(locator)
    if not p.exists():
        raise FileNotFoundError(locator)
    return p


def exists(locator: str) -> bool:
    try:
        p = resolve(locator)
        return p.exists()
    except Exception:
        return False
