# NewtonEDMS — Feature fusion map

NewtonEDMS is a single FastAPI application that combines LogicalDoc’s
enterprise repository model with Docspell’s automated document organizer.
This file is the inventory of what is implemented in-product (not a dump of
the upstream Java/Scala trees).

## Architecture

| Layer | LogicalDoc analogue | Docspell analogue | NewtonEDMS |
|---|---|---|---|
| Web UI | GWT webapp | Elm SPA | `frontend/index.html` (light/dark) |
| REST API | REST/SOAP/CMIS | OpenAPI REST | FastAPI `/api/*` + `/docs` |
| Processing | synchronous index | JOEX job executor | `app/joex.py` + `processing_jobs` |
| Search | Solr | Solr / Postgres FTS | Whoosh + query language |
| Identity | users/groups/ACL | collective + users | collectives, users, groups, ACL |
| Storage | file/DB/S3 | file/DB/S3 | local `storage/` (SQL URL swappable) |

## LogicalDoc capabilities

| Feature | Status |
|---|---|
| Mass / bulk upload | Yes (`POST /api/documents/bulk`) |
| Import folders | Yes |
| Email import (IMAP) | Yes + stored mail settings |
| Hierarchical folders | Yes |
| Metadata templates | Yes |
| Custom identifiers | Yes (`custom_id`) |
| Retention policies | Yes |
| RBAC + folder/document ACL | Yes |
| Versioning / checkout | Yes |
| Comments & annotations | Yes |
| Secure sharing | Yes, password-optional |
| Workflow + tasks | Yes |
| Notifications | Yes + query rules |
| Calendar | Yes |
| Reports / facets | Yes |
| Backup | Yes |
| Audit trail | Yes |
| REST API | Yes |
| TOTP 2FA | Yes |
| Encryption in transit | HTTPS / HSTS when `COOKIE_SECURE` |
| OCR / barcodes | Yes (tesseract / pyzbar, best-effort) |

## Docspell capabilities

| Feature | Status |
|---|---|
| Multi-account (collectives) | Yes |
| Multiple files as one item | Yes (attachments) |
| OCR + text extraction | Yes (JOEX) |
| Full-text search | Yes |
| Query language | Yes (`app/querylang.py`) |
| Bookmarks | Yes |
| Dashboards | Yes (`/api/dashboards/home`) |
| Non-destructive originals | Yes |
| Tags + custom fields | Yes |
| NLP metadata suggestions | Yes (catalog + regex dates) |
| Job management (cancel / priority) | Yes |
| Anonymous upload URLs | Yes (`/u/{token}`) |
| Password shares | Yes |
| Send via e-mail | Yes (SMTP settings) |
| IMAP mailbox import | Yes |
| Multi-edit | Yes |
| Merge items | Yes |
| Duplicate detection | Yes (SHA-256) |
| Zip / EML extraction | Yes |
| TOTP | Yes |
| OpenID / SSO | Not in this release (JWT + TOTP) |
| Addons | Webhooks on `on_process` |
| Dark / light theme | Yes |

## Processing pipeline (JOEX)

On every upload (and on `POST /api/documents/{id}/reprocess`):

1. Copy untouched original
2. SHA-256 hash + duplicate link
3. Extract zip / eml attachments
4. Extract text (office, PDF, OCR)
5. Suggest tags, contacts, dates, language
6. Update Whoosh index
7. Fire enabled addon webhooks

Set `EDMS_JOEX_INLINE=true` to run the pipeline in-request (used by tests).

## Microsoft Office Integration

| Capability | NewtonEDMS Implementation |
|---|---|
| Microsoft WOPI Protocol | Full standard WOPI Host (`/wopi/files/{id}`, `/wopi/files/{id}/contents`) supporting CheckFileInfo, GetFile, PutFile, Lock, Unlock, RefreshLock, GetLock, PutRelative, Rename, and Delete |
| In-Browser Office Online Editor | Interactive iframe workspace loader (`/api/office/wopi/frame/{id}`) supporting Collabora, OnlyOffice, Office Online Server, and Microsoft 365 |
| Desktop Office URI Launchers | One-click launch with `ms-word:ofe|u|...`, `ms-excel:ofe|u|...`, `ms-powerpoint:ofe|u|...` direct tokenized URI protocol handlers |
| Microsoft 365 / Office Add-in | Multi-host taskpane Add-in with XML v1.1 and M365 JSON manifests for Word, Excel, PowerPoint, and Outlook (`/api/office/addin/*`) |
| Outlook Email & Attachment Capture | 1-click email archiving into HTML dossiers with automated attachment extraction directly from Outlook Add-in (`/api/office/outlook/archive`) |
| OpenXML Metadata Synchronization | Bi-directional inspection and synchronization of core and custom OpenXML properties for `.docx`, `.xlsx`, `.pptx` (`app/office_meta.py`) |
| Dynamic Template Merging | Automated `{{placeholder}}` replacement across Word paragraphs, tables, headers, and Excel worksheets (`/api/office/templates/{id}/merge`) |
| Report & Dossier Exporters | Styled `.xlsx` spreadsheet generator and formatted `.docx` document summary dossier generator (`/api/office/export/excel`, `/api/office/export/word`) |
| Admin & Configuration | Office Add-in management, manifest downloading, sideload instructions, and WOPI client configuration in Admin Console |
