"""FastAPI application factory: middleware, routers, lifespan, static serving."""

import logging
import warnings
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import HTMLResponse
from fastapi.staticfiles import StaticFiles
from slowapi import _rate_limit_exceeded_handler
from slowapi.errors import RateLimitExceeded
from slowapi.middleware import SlowAPIMiddleware

from app.config import _DEV_SECRET, cors_origins, settings
from app.database import FRONTEND_DIR
from app.limiter import limiter
from app.routers import audit as audit_router
from app.routers import auth, collab, documents, extras, folders, groups, ingestion, system, users, workflow
from app.seeding import init_db

logger = logging.getLogger("newedms")


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
    logger.info("NewEDMS started (log_level=%s)", settings.log_level)
    yield
    logger.info("NewEDMS shutting down")


app = FastAPI(
    title="NewEDMS",
    description="Enterprise Document Management System",
    version="0.1.0",
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
async def security_headers(request: Request, call_next):
    """Attach defensive browser headers to every response."""
    response = await call_next(request)
    response.headers.setdefault("X-Content-Type-Options", "nosniff")
    response.headers.setdefault("X-Frame-Options", "DENY")
    response.headers.setdefault("Referrer-Policy", "no-referrer")
    response.headers.setdefault("Permissions-Policy", "geolocation=(), microphone=(), camera=()")
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
app.include_router(folders.router)
app.include_router(documents.router)
app.include_router(ingestion.router)
app.include_router(collab.router)
app.include_router(workflow.router)
app.include_router(extras.router)
app.include_router(audit_router.router)


@app.get("/", response_class=HTMLResponse, include_in_schema=False)
def root():
    index = FRONTEND_DIR / "index.html"
    if not index.exists():
        return HTMLResponse(
            "<h1>NewEDMS API is running</h1><p>Open /docs for API documentation.</p>"
        )
    return HTMLResponse(index.read_text(encoding="utf-8"))


app.mount("/static", StaticFiles(directory=FRONTEND_DIR), name="static")
