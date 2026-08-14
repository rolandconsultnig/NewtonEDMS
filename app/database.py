"""Database engine, session, declarative base, and path constants."""

from datetime import datetime
from pathlib import Path

from sqlalchemy import create_engine, event
from sqlalchemy.orm import declarative_base, sessionmaker

from app.config import BASE_DIR, settings

STORAGE_DIR = Path(settings.storage_dir) if settings.storage_dir else BASE_DIR / "storage"
FRONTEND_DIR = BASE_DIR / "frontend"
DB_PATH = BASE_DIR / "edms.db"
STORAGE_DIR.mkdir(parents=True, exist_ok=True)
FRONTEND_DIR.mkdir(parents=True, exist_ok=True)


def now() -> datetime:
    return datetime.utcnow()


def create_db_engine(url: str, **kwargs):
    """Create an engine, enabling SQLite foreign-key enforcement per connection.

    SQLite does not enforce FK constraints unless ``PRAGMA foreign_keys`` is set
    on every connection; without it, deletes silently orphan child rows.
    """
    opts: dict = {"pool_pre_ping": True}
    if url.startswith("sqlite"):
        opts["connect_args"] = {"check_same_thread": False}
    opts.update(kwargs)
    eng = create_engine(url, **opts)
    if url.startswith("sqlite"):

        @event.listens_for(eng, "connect")
        def _set_sqlite_fk_pragma(dbapi_connection, connection_record):  # noqa: ANN001
            cursor = dbapi_connection.cursor()
            cursor.execute("PRAGMA foreign_keys=ON")
            cursor.close()

    return eng


_database_url = settings.database_url or f"sqlite:///{DB_PATH}"
engine = create_db_engine(_database_url)
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
Base = declarative_base()


def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
