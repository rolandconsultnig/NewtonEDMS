"""FastAPI application factory: middleware, routers, lifespan, static serving."""

import logging
import warnings
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, HTMLResponse
from fastapi.staticfiles import StaticFiles
from slowapi import _rate_limit_exceeded_handler
from slowapi.errors import RateLimitExceeded
from slowapi.middleware import SlowAPIMiddleware

from app.branding import PRODUCT_DESCRIPTION, PRODUCT_NAME, PRODUCT_VERSION
from app.config import _DEV_SECRET, cors_origins, settings
from app.database import FRONTEND_DIR
from app.joex import start_worker, stop_worker
from app.limiter import limiter
from app.routers import audit as audit_router
from app.routers import (
    accounting,
    auth,
    collab,
    documents,
    extras,
    folders,
    groups,
    ingestion,
    insurance,
    legal,
    medical,
    newton,
    office,
    system,
    users,
    workflow,
)
from app import wopi
from app.routers import ce as ce_router
from app.routers import intel as intel_router
from app.routers import enterprise as enterprise_router
from app.protocols import cmis, soap, webdav
from app.scheduler import start_scheduler, stop_scheduler
from app.seeding import init_db
from app.smtp_gateway import start_gateway, stop_gateway

logger = logging.getLogger("newtonedms")


@asynccontextmanager
async def lifespan(_app: FastAPI):
    logging.basicConfig(
        level=getattr(logging, settings.log_level.upper(), logging.INFO),
        format="%(asctime)s %(levelname)s [%(name)s] %(message)s",
    )
    init_db()
    if settings.secret_key == _DEV_SECRET:
        warnings.warn(
            "EDMS_SECRET_KEY is the insecure default — set EDMS_SECRET_KEY in production!",
            RuntimeWarning,
            stacklevel=2,
        )
    if settings.joex_enabled and not settings.joex_inline:
        start_worker()
    start_scheduler()
    start_gateway()
    try:
        from app.cluster import heartbeat

        heartbeat("api")
    except Exception:
        logger.exception("cluster heartbeat failed")
    logger.info("%s started (log_level=%s)", PRODUCT_NAME, settings.log_level)
    yield
    stop_scheduler()
    stop_worker()
    stop_gateway()
    logger.info("%s shutting down", PRODUCT_NAME)


app = FastAPI(
    title=PRODUCT_NAME,
    description=PRODUCT_DESCRIPTION,
    version=PRODUCT_VERSION,
    lifespan=lifespan,
)

# Rate limiting
app.state.limiter = limiter
app.add_exception_handler(RateLimitExceeded, _rate_limit_exceeded_handler)
app.add_middleware(SlowAPIMiddleware)

# CORS (configurable allowlist)
app.add_middleware(
    CORSMiddleware,
    allow_origins=cors_origins(),
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.middleware("http")
async def path_normalization_middleware(request: Request, call_next):
    """Normalize accidentally duplicated /api/api/ prefixes."""
    if request.scope.get("path", "").startswith("/api/api/"):
        request.scope["path"] = request.scope["path"][4:]
    return await call_next(request)


@app.middleware("http")
async def security_headers(request: Request, call_next):
    """Attach defensive browser headers to every response."""
    response = await call_next(request)
    response.headers.setdefault("X-Content-Type-Options", "nosniff")
    
    path = request.url.path
    is_framable = (
        path.startswith("/wopi")
        or path.startswith("/api/office/wopi")
        or path.startswith("/static/office-addin")
        or path.startswith("/api/shares")
        or "/wopi/frame" in path
    )
    if is_framable:
        # Allow embedding in Office 365, Teams, OnlyOffice, Collabora, and local preview
        if "x-frame-options" in response.headers:
            del response.headers["x-frame-options"]
        if "X-Frame-Options" in response.headers:
            del response.headers["X-Frame-Options"]
        response.headers.setdefault(
            "Content-Security-Policy",
            "frame-ancestors 'self' https://*.office.com https://*.office365.com https://*.live.com https://*.microsoft.com https://*.sharepoint.com http://* https://*;",
        )
    else:
        response.headers.setdefault("X-Frame-Options", "DENY")
        
    response.headers.setdefault("Referrer-Policy", "no-referrer")
    response.headers.setdefault("Permissions-Policy", "geolocation=(), microphone=(), camera=(self)")
    if settings.cookie_secure:
        response.headers.setdefault(
            "Strict-Transport-Security", "max-age=31536000; includeSubDomains"
        )
    return response


# Routers
app.include_router(system.router)
app.include_router(auth.router)
app.include_router(users.router)
app.include_router(groups.router)
app.include_router(intel_router.router)
app.include_router(intel_router.open_intel)
app.include_router(enterprise_router.router)
app.include_router(enterprise_router.open_ent)
app.include_router(folders.router)
app.include_router(documents.router)
app.include_router(ingestion.router)
app.include_router(collab.router)
app.include_router(collab.open_collab)
app.include_router(workflow.router)
app.include_router(extras.router)
app.include_router(wopi.router)
app.include_router(office.router)
app.include_router(legal.router)
app.include_router(accounting.router)
app.include_router(insurance.router)
app.include_router(medical.router)
app.include_router(newton.router)
app.include_router(newton.open_router)
app.include_router(audit_router.router)
app.include_router(ce_router.router)
app.include_router(ce_router.open_ce)
app.include_router(webdav)
app.include_router(cmis)
app.include_router(soap)


@app.get("/", response_class=HTMLResponse, include_in_schema=False)
def root():
    index = FRONTEND_DIR / "index.html"
    if not index.exists():
        return HTMLResponse(
            f"<h1>{PRODUCT_NAME} API is running</h1><p>Open /docs for API documentation.</p>"
        )
    return HTMLResponse(index.read_text(encoding="utf-8"))


@app.get("/share.html", response_class=HTMLResponse, include_in_schema=False)
def share_page():
    page = FRONTEND_DIR / "share.html"
    if not page.exists():
        return HTMLResponse("missing", status_code=404)
    return HTMLResponse(page.read_text(encoding="utf-8"))


@app.get("/scan.html", response_class=HTMLResponse, include_in_schema=False)
def scan_page():
    page = FRONTEND_DIR / "scan.html"
    if not page.exists():
        return HTMLResponse("missing", status_code=404)
    return HTMLResponse(page.read_text(encoding="utf-8"))


@app.websocket("/ws/collab/{doc_id}")
async def collab_socket(websocket, doc_id: int):
    import json

    from app.collab_hub import broadcast, join, leave
    from app.database import SessionLocal
    from app.models import CollabOp, Document, User
    from app.security import decode_token

    await websocket.accept()
    user_id = None
    token = websocket.cookies.get(settings.cookie_name) if hasattr(websocket, "cookies") else None
    if token:
        try:
            payload = decode_token(token)
            sub = payload.get("sub")
            db = SessionLocal()
            try:
                u = db.query(User).filter(User.username == sub).first() if sub else None
                user_id = u.id if u else None
            finally:
                db.close()
        except Exception:
            user_id = None
    await join(doc_id, websocket)
    try:
        while True:
            data = await websocket.receive_text()
            try:
                op = json.loads(data)
            except Exception:
                op = {"text": data}
            db = SessionLocal()
            try:
                d = db.get(Document, int(doc_id))
                out = {"op": op, "user_id": user_id}
                if d:
                    d.collab_rev = (d.collab_rev or 0) + 1
                    db.add(CollabOp(document_id=d.id, rev=d.collab_rev, user_id=user_id, op=op if isinstance(op, dict) else {"raw": data}))
                    if isinstance(op, dict) and op.get("notes") is not None:
                        d.notes = str(op.get("notes"))
                    db.commit()
                    out["rev"] = d.collab_rev
            finally:
                db.close()
            await broadcast(doc_id, out, skip=websocket)
    except Exception:
        try:
            await websocket.close()
        except Exception:
            pass
    finally:
        await leave(doc_id, websocket)


@app.get("/favicon.ico", include_in_schema=False)
def favicon():
    icon = FRONTEND_DIR / "favicon.svg"
    if not icon.exists():
        return HTMLResponse(status_code=404)
    return FileResponse(icon, media_type="image/svg+xml")


app.mount("/static", StaticFiles(directory=FRONTEND_DIR), name="static")
