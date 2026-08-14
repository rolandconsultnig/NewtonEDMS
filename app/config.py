"""Application configuration (environment-driven)."""

from functools import lru_cache
from pathlib import Path
from typing import List

from pydantic_settings import BaseSettings, SettingsConfigDict

BASE_DIR = Path(__file__).resolve().parent.parent
_DEV_SECRET = "newedms-dev-secret-DO-NOT-USE-IN-PRODUCTION"


class Settings(BaseSettings):
    """Runtime configuration loaded from the environment (``EDMS_*`` prefix) or ``.env``."""

    model_config = SettingsConfigDict(
        env_file=BASE_DIR / ".env", env_prefix="EDMS_", extra="ignore"
    )

    secret_key: str = _DEV_SECRET
    algorithm: str = "HS256"
    access_token_expire_minutes: int = 240
    database_url: str = ""
    cors_origins: str = "http://localhost:8000,http://127.0.0.1:8000"
    storage_dir: str = ""
    max_upload_bytes: int = 50 * 1024 * 1024
    blocked_extensions: str = (
        "exe,bat,cmd,com,sh,ps1,js,vbs,msi,dll,scr,jar,wsf,hta,php,pl,py"
    )
    login_rate_limit: str = "5/minute"
    register_rate_limit: str = "10/hour"
    password_min_length: int = 8
    seed_admin_username: str = "admin"
    seed_admin_password: str = "admin123"
    server_host: str = "0.0.0.0"
    server_port: int = 8000
    # Auth cookie
    cookie_name: str = "edms_token"
    cookie_secure: bool = False  # set True behind HTTPS in production
    cookie_samesite: str = "lax"


@lru_cache
def get_settings() -> Settings:
    return Settings()


settings = get_settings()


def cors_origins() -> List[str]:
    return [o.strip() for o in settings.cors_origins.split(",") if o.strip()]
