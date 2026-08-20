"""Application configuration (environment-driven)."""

from functools import lru_cache
from pathlib import Path

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
    share_rate_limit: str = "10/minute"
    password_min_length: int = 8
    # Optional allowlist root that import-folders may watch. Empty = the import
    # folder feature refuses new folders (arbitrary-filesystem-read guard).
    # Empty string disables watched folders (tests). Default path is storage/imports.
    import_root: str = str(BASE_DIR / "storage" / "imports")
    max_extract_bytes: int = 20 * 1024 * 1024
    max_import_files_per_scan: int = 500
    seed_admin_username: str = "admin"
    seed_admin_password: str = "admin123"
    server_host: str = "0.0.0.0"
    server_port: int = 8000
    log_level: str = "INFO"
    # Auth cookie
    cookie_name: str = "newton_token"
    cookie_secure: bool = False  # set True behind HTTPS in production
    cookie_samesite: str = "lax"
    # JOEX (Docspell-style job executor)
    joex_enabled: bool = True
    joex_inline: bool = False  # process jobs in-request (tests / single-shot)
    joex_poll_seconds: float = 2.0
    smtp_from: str = "newtonedms@localhost"
    preview_dpi: int = 96
    joex_pool_size: int = 2
    joex_stuck_minutes: int = 30
    joex_max_attempts: int = 3
    solr_url: str = ""
    fts_backend: str = "auto"  # auto | whoosh | postgres | solr | sqlite
    cmd_tesseract: str = ""
    cmd_unoconv: str = ""
    cmd_wkhtmltopdf: str = ""
    cmd_ocrmypdf: str = ""
    smtp_gateway_enabled: bool = False
    smtp_gateway_host: str = "127.0.0.1"
    smtp_gateway_port: int = 2525
    oidc_issuer: str = ""
    oidc_client_id: str = ""
    oidc_client_secret: str = ""
    oidc_redirect_uri: str = ""
    s3_endpoint: str = ""
    s3_bucket: str = ""
    s3_access_key: str = ""
    s3_secret_key: str = ""
    s3_region: str = "us-east-1"
    classifier_retrain_hours: int = 24
    saml_idp_sso_url: str = ""
    saml_entity_id: str = ""
    saml_acs_url: str = ""
    saml_idp_cert: str = ""
    saml_require_signature: bool = False
    llm_url: str = ""
    llm_model: str = ""
    llm_api_key: str = ""
    azure_account: str = ""
    azure_container: str = ""
    azure_key: str = ""
    onlyoffice_url: str = ""
    onlyoffice_jwt: str = ""
    office_online_url: str = ""
    wopi_client_url: str = ""
    wopi_token_ttl_minutes: int = 1440
    office_addin_enabled: bool = True
    archivelink_secret: str = ""


@lru_cache
def get_settings() -> Settings:
    return Settings()


settings = get_settings()


def cors_origins() -> list[str]:
    return [o.strip() for o in settings.cors_origins.split(",") if o.strip()]
