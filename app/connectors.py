"""External connectors: Azure Blob, SMB, Google Drive, OnlyOffice, DocuSign, Outlook, SAP ArchiveLink helpers."""
from __future__ import annotations

import logging
from pathlib import Path
from urllib.parse import quote

from app.config import settings

logger = logging.getLogger("newtonedms.connectors")


def azure_upload(path: Path, key: str, cfg: dict) -> str:
    account = cfg.get("account") or getattr(settings, "azure_account", "")
    container = cfg.get("container") or getattr(settings, "azure_container", "")
    token = cfg.get("key") or getattr(settings, "azure_key", "")
    if not (account and container and token):
        raise ValueError("Azure Blob needs account, container, and key")
    try:
        from azure.storage.blob import BlobServiceClient

        client = BlobServiceClient(
            account_url=f"https://{account}.blob.core.windows.net", credential=token
        )
        blob = client.get_blob_client(container=container, blob=key)
        with path.open("rb") as fh:
            blob.upload_blob(fh, overwrite=True)
        return f"azure:{container}/{key}"
    except ImportError:
        import httpx

        url = f"https://{account}.blob.core.windows.net/{container}/{quote(key)}"
        headers = {
            "x-ms-blob-type": "BlockBlob",
            "x-ms-version": "2020-10-02",
            "Authorization": f"SharedKey {account}:{token}",
        }
        r = httpx.put(url, headers=headers, content=path.read_bytes(), timeout=30)
        if r.status_code >= 400:
            # SAS URL style: treat token as full SAS
            url = f"https://{account}.blob.core.windows.net/{container}/{quote(key)}?{token.lstrip('?')}"
            r = httpx.put(url, headers={"x-ms-blob-type": "BlockBlob", "x-ms-version": "2020-10-02"}, content=path.read_bytes(), timeout=30)
            r.raise_for_status()
        return f"azure:{container}/{key}"


def azure_download(locator: str, cfg: dict) -> Path:
    import tempfile

    import httpx

    _, rest = locator.split(":", 1)
    container, _, key = rest.partition("/")
    account = cfg.get("account") or getattr(settings, "azure_account", "")
    token = cfg.get("key") or getattr(settings, "azure_key", "")
    url = f"https://{account}.blob.core.windows.net/{container}/{quote(key)}"
    r = httpx.get(url, headers={"Authorization": f"SharedKey {account}:{token}"}, timeout=30)
    if r.status_code >= 400:
        url = f"{url}?{token.lstrip('?')}"
        r = httpx.get(url, timeout=30)
        r.raise_for_status()
    tmp = Path(tempfile.gettempdir()) / Path(key).name
    tmp.write_bytes(r.content)
    return tmp


def smb_list(cfg: dict) -> list[dict]:
    host = cfg.get("host")
    share = cfg.get("share")
    path = cfg.get("path") or ""
    user = cfg.get("username") or ""
    password = cfg.get("password") or ""
    try:
        from smbclient import listdir, register_session, stat

        register_session(host, username=user, password=password)
        root = f"\\\\{host}\\{share}\\{path}".replace("/", "\\")
        out = []
        for name in listdir(root):
            if name in (".", ".."):
                continue
            full = root.rstrip("\\") + "\\" + name
            try:
                info = stat(full)
                is_dir = bool(info.st_file_attributes & 0x10) if hasattr(info, "st_file_attributes") else False
            except Exception:
                is_dir = False
            out.append({"name": name, "path": full, "is_dir": is_dir})
        return out
    except ImportError:
        unc = Path(f"//{host}/{share}/{path}")
        if not unc.exists():
            raise ValueError("SMB library not installed and UNC path not reachable")
        return [{"name": p.name, "path": str(p), "is_dir": p.is_dir()} for p in unc.iterdir()]


def smb_fetch(cfg: dict, remote: str, dest: Path) -> Path:
    dest.parent.mkdir(parents=True, exist_ok=True)
    try:
        from smbclient import open_file, register_session

        register_session(cfg.get("host"), username=cfg.get("username") or "", password=cfg.get("password") or "")
        with open_file(remote, "rb") as src, dest.open("wb") as out:
            while True:
                chunk = src.read(1024 * 1024)
                if not chunk:
                    break
                out.write(chunk)
        return dest
    except ImportError:
        p = Path(remote)
        if p.exists():
            dest.write_bytes(p.read_bytes())
            return dest
        raise


def gdrive_list(access_token: str, query: str = "") -> list[dict]:
    import httpx

    params = {"pageSize": 50, "fields": "files(id,name,mimeType,modifiedTime)"}
    if query:
        params["q"] = f"name contains '{query.replace(chr(39), '')}'"
    r = httpx.get(
        "https://www.googleapis.com/drive/v3/files",
        params=params,
        headers={"Authorization": f"Bearer {access_token}"},
        timeout=20,
    )
    r.raise_for_status()
    return r.json().get("files") or []


def gdrive_download(access_token: str, file_id: str, dest: Path) -> Path:
    import httpx

    r = httpx.get(
        f"https://www.googleapis.com/drive/v3/files/{file_id}",
        params={"alt": "media"},
        headers={"Authorization": f"Bearer {access_token}"},
        timeout=60,
        follow_redirects=True,
    )
    r.raise_for_status()
    dest.write_bytes(r.content)
    return dest


def onlyoffice_config(doc_id: int, title: str, download_url: str, callback_url: str, key: str) -> dict:
    cfg = {
        "document": {
            "fileType": Path(title).suffix.lstrip(".") or "docx",
            "key": key,
            "title": title,
            "url": download_url,
        },
        "documentType": "word",
        "editorConfig": {
            "callbackUrl": callback_url,
            "mode": "edit",
        },
    }
    jwt_secret = getattr(settings, "onlyoffice_jwt", "") or ""
    if jwt_secret:
        from jose import jwt

        cfg["token"] = jwt.encode(cfg, jwt_secret, algorithm="HS256")
    return cfg


def docusign_send(cfg: dict, pdf: Path, email: str, name: str) -> dict:
    """Create a DocuSign envelope when credentials exist; otherwise a local sign request."""
    base = (cfg.get("base_url") or "https://demo.docusign.net/restapi").rstrip("/")
    token = cfg.get("access_token") or ""
    account = cfg.get("account_id") or ""
    if token and account:
        import base64
        import httpx

        body = {
            "emailSubject": f"Please sign {pdf.name}",
            "documents": [
                {
                    "documentBase64": base64.b64encode(pdf.read_bytes()).decode(),
                    "name": pdf.name,
                    "fileExtension": "pdf",
                    "documentId": "1",
                }
            ],
            "recipients": {
                "signers": [{"email": email, "name": name, "recipientId": "1", "routingOrder": "1"}]
            },
            "status": "sent",
        }
        r = httpx.post(
            f"{base}/v2.1/accounts/{account}/envelopes",
            json=body,
            headers={"Authorization": f"Bearer {token}"},
            timeout=30,
        )
        r.raise_for_status()
        return r.json()
    return {"status": "local", "email": email, "file": str(pdf)}


def _graph_headers(cfg: dict) -> dict:
    token = cfg.get("access_token") or cfg.get("token") or ""
    if not token:
        raise ValueError("Microsoft Graph access_token is required")
    return {"Authorization": f"Bearer {token}"}


def graph_list_mail(cfg: dict, top: int = 25) -> list[dict]:
    import httpx

    r = httpx.get(
        "https://graph.microsoft.com/v1.0/me/messages",
        params={"$top": min(int(top or 25), 50), "$select": "id,subject,from,receivedDateTime,hasAttachments,bodyPreview"},
        headers=_graph_headers(cfg),
        timeout=30,
    )
    r.raise_for_status()
    out = []
    for m in r.json().get("value") or []:
        frm = ((m.get("from") or {}).get("emailAddress") or {})
        out.append(
            {
                "id": m.get("id"),
                "subject": m.get("subject"),
                "from": frm.get("address") or frm.get("name"),
                "received": m.get("receivedDateTime"),
                "has_attachments": bool(m.get("hasAttachments")),
                "preview": m.get("bodyPreview"),
            }
        )
    return out


def graph_download_mime(cfg: dict, message_id: str, dest: Path) -> Path:
    import httpx

    r = httpx.get(
        f"https://graph.microsoft.com/v1.0/me/messages/{message_id}/$value",
        headers=_graph_headers(cfg),
        timeout=60,
    )
    r.raise_for_status()
    dest.parent.mkdir(parents=True, exist_ok=True)
    dest.write_bytes(r.content)
    return dest


def graph_list_events(cfg: dict, top: int = 25) -> list[dict]:
    import httpx

    r = httpx.get(
        "https://graph.microsoft.com/v1.0/me/events",
        params={"$top": min(int(top or 25), 50), "$select": "id,subject,start,end,organizer"},
        headers=_graph_headers(cfg),
        timeout=30,
    )
    r.raise_for_status()
    return r.json().get("value") or []
