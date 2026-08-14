# NewEDMS — Enterprise Document Management System

A baseline multi-user, multi-level DMS inspired by LogicalDoc, built with Python FastAPI and a lightweight web UI.

## LogicalDoc feature inventory

See `LogicalDoc_Features.md` for the full list of LogicalDoc modules, capabilities and architecture.

## What is implemented in this V1

- **Multi-user authentication** (JWT) with role-based access: `superadmin`, `admin`, `manager`, `user`
- **Groups** with membership management
- **Hierarchical folders** with public/private visibility
- **Document upload, download, metadata, tags, status workflow**
- **Versioning** with history, restore, check-in/check-out
- **Search** by name, title, tags and metadata
- **RBAC + ACL permissions** on folders (read / write / delete / manage)
- **Audit trail** logging all document, user and permission events
- **REST API** (OpenAPI docs at `/docs`)
- **Web UI** with folder tree, uploads, version management, admin panels

## Quick start

1. Install dependencies:

```powershell
py -m pip install -r requirements.txt
```

2. (Recommended) configure the app. Copy `.env.example` to `.env` and adjust —
   in particular set `EDMS_SECRET_KEY` to a long random string for any non-local
   deployment. All settings use the `EDMS_` prefix; sensible dev defaults apply
   if no `.env` is present.

3. Run the application:

```powershell
py main.py
```

   …or with uvicorn (now also supported — the database is initialized via a
   startup hook):

```powershell
uvicorn main:app --host 0.0.0.0 --port 8000
```

4. Open `http://localhost:8000` in a browser.

Default credentials (first-boot seeding only — change immediately):

- **Username:** `admin`
- **Password:** `admin123`

API documentation is available at `http://localhost:8000/docs`.

## Configuration

All runtime settings are read from environment variables (prefix `EDMS_`) or a
`.env` file at the project root. Key options:

| Variable | Default | Purpose |
|----------|---------|---------|
| `EDMS_SECRET_KEY` | insecure dev value | JWT signing key. **Must** be overridden in production. |
| `EDMS_ACCESS_TOKEN_EXPIRE_MINUTES` | `240` | Token lifetime. |
| `EDMS_DATABASE_URL` | local `./edms.db` | SQLAlchemy URL (e.g. Postgres for production). |
| `EDMS_CORS_ORIGINS` | `http://localhost:8000,...` | Comma-separated allowed origins. |
| `EDMS_STORAGE_DIR` | `./storage` | Where uploaded files are stored. |
| `EDMS_MAX_UPLOAD_BYTES` | `52428800` (50 MiB) | Per-file upload size cap. |
| `EDMS_BLOCKED_EXTENSIONS` | `exe,bat,cmd,...` | Comma-separated blocked file extensions. |
| `EDMS_LOGIN_RATE_LIMIT` | `5/minute` | Login throttling (slowapi syntax). |
| `EDMS_SEED_ADMIN_USERNAME` / `EDMS_SEED_ADMIN_PASSWORD` | `admin` / `admin123` | First-boot admin seed. |
| `EDMS_COOKIE_NAME` / `EDMS_COOKIE_SECURE` / `EDMS_COOKIE_SAMESITE` | `edms_token` / `false` / `lax` | Auth cookie. Set `SECURE=true` behind HTTPS. |

## Production deployment

### Quick start (Docker, single node)

```powershell
docker build -t newedms .
docker volume create edms-data
docker run -d --name newedms -p 8000:8000 \
  -e EDMS_SECRET_KEY=$(openssl rand -hex 32) \
  -e EDMS_SEED_ADMIN_PASSWORD=change-me-now \
  -v edms-data:/data newedms
```

The container runs `alembic upgrade head` on boot and serves with uvicorn
(1 worker — see the SQLite note below). Health probe: `GET /api/system/health`.

### Production checklist

- [ ] **`EDMS_SECRET_KEY`** — long random value (the app warns loudly on the default).
- [ ] **Change the seeded admin password** immediately after first login.
- [ ] **HTTPS** — terminate TLS at a reverse proxy, then set
      `EDMS_COOKIE_SECURE=true` (also enables HSTS).
- [ ] **CORS** — set `EDMS_CORS_ORIGINS` to your exact UI origin(s).
- [ ] **Backups** — schedule `POST /api/backup` (consistent SQLite snapshot +
      documents; keeps the last 5) and copy the zips off-host.
- [ ] **Rate limits** — review `EDMS_LOGIN_RATE_LIMIT` / `EDMS_REGISTER_RATE_LIMIT`
      / `EDMS_SHARE_RATE_LIMIT`.
- [ ] **Import folders** — disabled unless `EDMS_IMPORT_ROOT` is set; point it at
      a dedicated directory you intend to expose, never a system or app path.
- [ ] **Email import** — consider a dedicated service account; credentials are
      supplied per-request and never stored.

### Operational notes & limits

- **SQLite + local storage = single-node, single-worker.** The schema is
  portable: set `EDMS_DATABASE_URL` to Postgres for multi-worker deployments
  (then also move `EDMS_STORAGE_DIR` to shared/object storage).
- Retention-policy "delete", document deletion, and import-folder scans with
  "move" mode permanently destroy files — test policies on copies first.
- Share links are unauthenticated URLs: they always expire (default 7 days) and
  enforce `max_downloads` atomically, but treat every link as public.
- Logs go to stdout (`EDMS_LOG_LEVEL`); point your collector at container logs.

## Authentication model

Sessions use an **HttpOnly cookie** issued on login/register (`SameSite=Lax`).
The API also still accepts `Authorization: Bearer <token>` for CLI/OpenAPI use.
Each JWT carries a `jti`; `POST /api/auth/logout` revokes it (stored in
`revoked_tokens`) and clears the cookie, so a logged-out token stops working
even if copied. Bearer tokens previously stored in `localStorage` are no longer
used by the UI.

## Frontend assets

The SPA uses a **compiled** Tailwind stylesheet (`frontend/tailwind.css`), not
the CDN. Rebuild it after changing classes:

```powershell
npm install
npm run build:css      # one-off minified build
npm run watch:css      # rebuild on change during development
```

## Testing

```powershell
py -m pip install -r requirements-dev.txt
pytest
```

The suite uses FastAPI's `TestClient` against an in-memory SQLite database and a
temporary storage directory, so it runs in isolation and does not touch the real
`edms.db` or `storage/` folder.

## Project layout

```
NewEDMS/
  main.py                # Uvicorn launcher (boots app.main:app)
  app/
    main.py              # FastAPI app: lifespan, middleware, router wiring, SPA root
    config.py            # Environment-driven Settings (EDMS_* prefix)
    database.py          # engine, SessionLocal, Base, get_db, paths
    models.py            # SQLAlchemy ORM models
    schemas.py           # Pydantic request/response schemas
    security.py          # password hashing, JWT, get_current_user / require_role
    permissions.py       # RBAC/ACL checks + SQL visibility helpers
    storage.py           # filename safety, upload size/extension policy
    audit.py             # audit-log helper
    seeding.py           # first-boot DB init + admin seed
    limiter.py           # shared slowapi limiter
    routers/             # auth, users, groups, folders, documents, audit
  frontend/index.html    # SPA web interface
  frontend/src/input.css # Tailwind entry (npm run build:css -> frontend/tailwind.css)
  package.json           # Tailwind toolchain (npm)
  tailwind.config.js
  alembic/               # Database migrations (alembic upgrade head)
  alembic.ini
  requirements.txt       # Runtime dependencies
  requirements-dev.txt   # Test/lint dependencies
  tests/                 # pytest suite (isolated in-memory SQLite)
  storage/               # Uploaded files (created at runtime)
  edms.db                # SQLite database (created at runtime)
  LogicalDoc_Features.md
  README.md
```

## Architecture notes

- Layered FastAPI app in the `app/` package (config → database → models → security/permissions/storage → routers → main).
- SQLite for metadata (swap via `EDMS_DATABASE_URL`, e.g. Postgres for production), local `storage/` for file content.
- Schema changes are managed with **Alembic** (`alembic upgrade head`); tables are also created on startup for dev convenience.
- JWT bearer auth; hierarchical permissions fall back through parent folders.
- Document visibility is pushed into SQL (no per-row permission queries).
- File versions are stored under `storage/doc_<id>/v{N}<ext>`.
