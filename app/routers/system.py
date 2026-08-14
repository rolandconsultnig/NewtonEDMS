"""System routes: health/readiness probe (unauthenticated, no sensitive data)."""

from fastapi import APIRouter
from sqlalchemy import text

from app import database

router = APIRouter(prefix="/api/system", tags=["system"])


@router.get("/health")
def health():
    """Liveness/readiness probe: verifies DB connectivity and storage writability."""
    checks = {}
    try:
        with database.engine.connect() as conn:
            conn.execute(text("SELECT 1"))
        checks["database"] = "ok"
    except Exception as exc:  # pragma: no cover - only on real failures
        checks["database"] = f"error: {type(exc).__name__}"

    try:
        probe = database.STORAGE_DIR / ".health_probe"
        probe.write_text("ok", encoding="utf-8")
        probe.unlink(missing_ok=True)
        checks["storage"] = "ok"
    except Exception as exc:  # pragma: no cover
        checks["storage"] = f"error: {type(exc).__name__}"

    healthy = all(v == "ok" for v in checks.values())
    return {"status": "ok" if healthy else "degraded", "checks": checks}
