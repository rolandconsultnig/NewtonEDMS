"""Database initialization / first-boot seeding.

Accesses ``engine``/``SessionLocal``/``Base`` through the ``database`` module so
that tests can rebind them and have the startup hook use the test engine.
"""

from app import database
from app.config import settings
from app.models import Folder, User
from app.security import pwd_context


def init_db() -> None:
    database.Base.metadata.create_all(bind=database.engine)
    db = database.SessionLocal()
    try:
        if not db.query(User).first():
            admin = User(
                username=settings.seed_admin_username,
                email="admin@newedms.local",
                hashed_password=pwd_context.hash(settings.seed_admin_password),
                role="superadmin",
                is_active=True,
            )
            db.add(admin)
            db.commit()
            db.refresh(admin)
        if not db.query(Folder).filter(Folder.parent_id.is_(None)).first():
            admin = (
                db.query(User)
                .filter(User.username == settings.seed_admin_username)
                .first()
            )
            root = Folder(name="Root", parent_id=None, is_public=True, created_by=admin.id)
            db.add(root)
            db.commit()
    finally:
        db.close()
