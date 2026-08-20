"""Database initialization / first-boot seeding.

Accesses ``engine``/``SessionLocal``/``Base`` through the ``database`` module so
that tests can rebind them and have the startup hook use the test engine.
"""

from app import database
from app.branding import DEFAULT_COLLECTIVE, PRODUCT_NAME
from app.config import settings
from app.models import Collective, Folder, Tag, User
from app.schema_upgrade import ensure_columns
from app.security import get_password_hash
import secrets

_DEFAULT_TAGS = (
    ("invoice", "finance"),
    ("receipt", "finance"),
    ("contract", "legal"),
    ("letter", "correspondence"),
    ("statement", "finance"),
    ("identity", "personal"),
    ("tax", "finance"),
    ("medical", "personal"),
)


def init_db() -> None:
    database.Base.metadata.create_all(bind=database.engine)
    ensure_columns(database.engine)
    db = database.SessionLocal()
    try:
        collective = db.query(Collective).filter(Collective.name == DEFAULT_COLLECTIVE).first()
        if not collective:
            collective = Collective(
                name=DEFAULT_COLLECTIVE,
                description=f"Default {PRODUCT_NAME} collective",
                invite_code=secrets.token_urlsafe(12),
                language="eng",
                classifier_config={"whitelist": [], "blacklist": ["workflow"]},
                settings={"preview_dpi": 96},
            )
            db.add(collective)
            db.commit()
            db.refresh(collective)
        if collective and not collective.invite_code:
            collective.invite_code = secrets.token_urlsafe(12)
            db.commit()

        if not db.query(User).first():
            admin = User(
                username=settings.seed_admin_username,
                email="admin@newtonedms.local",
                hashed_password=get_password_hash(settings.seed_admin_password),
                role="superadmin",
                is_active=True,
                collective_id=collective.id,
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
        if not db.query(Tag).first():
            admin = db.query(User).filter(User.username == settings.seed_admin_username).first()
            for name, category in _DEFAULT_TAGS:
                db.add(Tag(name=name, category=category, created_by=admin.id if admin else None))
            db.commit()
    finally:
        db.close()
