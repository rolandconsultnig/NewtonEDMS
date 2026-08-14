"""Database engine, session, declarative base, and path constants."""

from datetime import datetime
from pathlib import Path

from sqlalchemy import create_engine
from sqlalchemy.orm import declarative_base, sessionmaker

from app.config import BASE_DIR, settings

STORAGE_DIR = Path(settings.storage_dir) if settings.storage_dir else BASE_DIR / "storage"
FRONTEND_DIR = BASE_DIR / "frontend"
DB_PATH = BASE_DIR / "edms.db"
STORAGE_DIR.mkdir(parents=True, exist_ok=True)
FRONTEND_DIR.mkdir(parents=True, exist_ok=True)


def now() -> datetime:
    return datetime.utcnow()


_database_url = settings.database_url or f"sqlite:///{DB_PATH}"
engine = create_engine(
    _database_url,
    connect_args={"check_same_thread": False} if _database_url.startswith("sqlite") else {},
    pool_pre_ping=True,
)
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
Base = declarative_base()


def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
