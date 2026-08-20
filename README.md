# NewtonEDMS — LogicalDoc × Docspell fusion

NewtonEDMS is an enterprise document management system that fuses **LogicalDoc**’s
folder-centric governance with **Docspell**’s intelligent capture pipeline.
The product name is NewtonEDMS; the runtime is the existing FastAPI stack in
this repository (not a wrapper around the upstream Java/Scala codebases).

Upstream sources remain in `community-master/` (LogicalDoc) and
`docspell-master/` (Docspell) as feature references. The running system is
Python: FastAPI + SQLAlchemy + a JOEX job executor.

See `NewtonEDMS_Features.md` for the full feature map.

## What you get

### From LogicalDoc (repository & governance)

- Hierarchical folders with RBAC + ACL
- Versioning, check-in / check-out, restore
- Workflow templates, tasks, notifications
- Retention policies, audit trail, backup
- Comments / annotations, metadata templates
- Share links (now also password-protected)
- Import folders and IMAP ingestion
- Faceted search, reports, calendar

### From Docspell (capture & intelligence)

- **JOEX** background processing: hash, OCR/text extract, NLP suggestions, index
- Address book (correspondent / concerning)
- Query language (`tag:invoice due:overdue correspondent:acme`)
- Saved query bookmarks and home dashboards
- Custom typed fields, tag catalog, auto-tagging
- Anonymous upload URLs with pre-applied metadata
- Multi-file items (attachments), zip/eml extraction
- Duplicate detection via content hash
- Merge + multi-edit
- TOTP two-factor authentication
- SMTP send / stored IMAP settings
- Dark / light theme, processing inbox
- Addon webhooks after processing
- Non-destructive originals

### Microsoft Office Integration

- **Standard WOPI Host Protocol**: Full Microsoft WOPI host implementation (`/wopi/files/{id}`) with locks, revisions, and in-browser Office Online workspace editor.
- **Desktop Office Protocol Handlers**: Direct `ms-word:`, `ms-excel:`, `ms-powerpoint:` desktop launching with seamless checkout/check-in.
- **Microsoft 365 / Office Add-in Suite**: Multi-host taskpane Add-in for Word, Excel, PowerPoint, and Outlook (XML v1.1 & M365 JSON manifests).
- **Outlook Email Archiving**: 1-click email and attachment capture directly from Microsoft Outlook.
- **OpenXML Metadata Synchronization**: Bi-directional inspection and synchronization of core and custom OpenXML properties for `.docx`, `.xlsx`, `.pptx`.
- **Dynamic Template Merging**: Placeholder replacement engine (`{{key}}`) across paragraphs, tables, and worksheets for automated contract and document generation.
- **Executive Export Engine**: Generate styled `.xlsx` reports with zebra striping and `.docx` dossiers directly from repository search results.

## Quick start

1. Install dependencies:

```powershell
py -m pip install -r requirements.txt
```

2. Copy `.env.example` to `.env` and set `EDMS_SECRET_KEY` for any non-local deploy.

3. Run:

```powershell
py main.py
```

or:

```powershell
uvicorn app.main:app --host 0.0.0.0 --port 8000
```

4. Open `http://localhost:8000`.

Default credentials (first-boot only — change immediately):

- **Username:** `admin`
- **Password:** `admin123`

API docs: `http://localhost:8000/docs`.

## Query language

The search box accepts Docspell-style filters:

```
tag:invoice correspondent:acme due:overdue status:draft
folder:3 source:email inbox "purchase order"
```

Known fields: `tag`, `correspondent`, `concerning`, `status`, `folder`, `due`
(`overdue` / `none` / `YYYY-MM`), `source`, `lang`, `id`, `name`, `hash`,
`notes`, `custom`, `inbox`, `direction`, `equipment`. Remaining words are
full-text.

## Configuration

All runtime settings use the `EDMS_` prefix (unchanged for compatibility) or a
`.env` file. Key options:

| Variable | Default | Purpose |
|---|---|---|
| `EDMS_SECRET_KEY` | insecure dev value | JWT signing key. **Must** be overridden in production. |
| `EDMS_ACCESS_TOKEN_EXPIRE_MINUTES` | `240` | Token lifetime. |
| `EDMS_DATABASE_URL` | local `./edms.db` | SQLAlchemy URL (e.g. Postgres for production). |
| `EDMS_CORS_ORIGINS` | `http://localhost:8000,...` | Comma-separated allowed origins. |
| `EDMS_STORAGE_DIR` | `./storage` | Where uploaded files are stored. |
| `EDMS_MAX_UPLOAD_BYTES` | `52428800` (50 MiB) | Per-file upload size cap. |
| `EDMS_BLOCKED_EXTENSIONS` | `exe,bat,cmd,...` | Comma-separated blocked file extensions. |
| `EDMS_LOGIN_RATE_LIMIT` | `5/minute` | Login throttling. |
| `EDMS_JOEX_ENABLED` | `true` | Background job worker. |
| `EDMS_JOEX_INLINE` | `false` | Process jobs in-request (tests). |
| `EDMS_COOKIE_NAME` | `newton_token` | Auth cookie. Set `EDMS_COOKIE_SECURE=true` behind HTTPS. |

## Production deployment (Ubuntu server)

Run directly on the server with systemd + nginx. Ready-made configs are in
`deploy/` (`newedms.service`, `nginx-newedms.conf`).

### Install

```bash
# 1. System user + directories
sudo useradd --system --home /opt/newedms --shell /usr/sbin/nologin newedms
sudo mkdir -p /opt/newedms /var/lib/newedms /etc/newedms
sudo chown -R newedms:newedms /var/lib/newedms

# 2. Application code + virtualenv (Python 3.12)
sudo rsync -a --exclude node_modules --exclude .git ./ /opt/newedms/
cd /opt/newedms
sudo python3.12 -m venv venv
sudo ./venv/bin/pip install -r requirements.lock

# 3. Environment file (see .env.example; chmod 600, owner newedms)
sudo tee /etc/newedms/newedms.env >/dev/null <<'EOF'
EDMS_SECRET_KEY=<openssl rand -hex 32>
EDMS_STORAGE_DIR=/var/lib/newedms/storage
EDMS_DATABASE_URL=sqlite:////var/lib/newedms/edms.db
EDMS_SEED_ADMIN_PASSWORD=change-me-now
EOF
sudo chown newedms:newedms /etc/newedms/newedms.env && sudo chmod 600 /etc/newedms/newedms.env

# 4. Service + reverse proxy
sudo cp deploy/newedms.service /etc/systemd/system/
sudo systemctl daemon-reload && sudo systemctl enable --now newedms
sudo cp deploy/nginx-newedms.conf /etc/nginx/sites-available/newedms
sudo ln -s /etc/nginx/sites-available/newedms /etc/nginx/sites-enabled/
sudo nginx -t && sudo systemctl reload nginx

# 5. TLS (then set EDMS_COOKIE_SECURE=true and restart)
sudo certbot --nginx -d edms.example.com
```

Health probe: `GET /api/system/health`. Logs: `journalctl -u newedms -f`.

### Switching to PostgreSQL (multi-worker)

SQLite is single-writer: keep `--workers 1` in `deploy/newedms.service`. For
more workers on the same server, use Postgres:

```bash
sudo apt install postgresql
sudo -u postgres createuser newedms && sudo -u postgres createdb -O newedms edms
sudo ./venv/bin/pip install psycopg2-binary
# /etc/newedms/newedms.env:
#   EDMS_DATABASE_URL=postgresql+psycopg2://newedms:PASSWORD@localhost/edms
```

Then raise `--workers`. Two caveats at >1 worker: the in-memory rate limiter
counts per worker, and the file-based Whoosh index is written via AsyncWriter
(keep uploads on one worker or move search to a dedicated backend). Validate
the target database with the full suite first:

```bash
EDMS_TEST_DATABASE_URL=postgresql+psycopg2://newedms:PASSWORD@localhost/edms_test \
    ./venv/bin/pytest
```

### Optional: Docker

A `Dockerfile` is included for container-based deployments (single-node,
migrations run on boot). Not required for the Ubuntu path above.

## Testing

```powershell
py -m pip install -r requirements-dev.txt
pytest
```

## Project layout

```
NewEDMS/
  main.py
  app/
    branding.py          # NewtonEDMS product identity
    joex.py              # Docspell-style job executor
    nlp.py               # date/tag/contact suggestions
    querylang.py         # query language
    totp.py              # RFC 6238 two-factor
    extract.py           # zip / eml extraction
    routers/newton.py    # fusion APIs
    ...
  frontend/index.html
  alembic/
  tests/
  NewtonEDMS_Features.md
  LogicalDoc_Features.md
  README.md
```
