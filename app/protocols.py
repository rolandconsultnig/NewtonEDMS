"""WebDAV, CMIS Browser, and SOAP adapters over the same repository."""
from __future__ import annotations

import xml.etree.ElementTree as ET
from pathlib import Path
from urllib.parse import unquote

from fastapi import APIRouter, Depends, HTTPException, Request, Response
from fastapi.security import HTTPBasic, HTTPBasicCredentials
from fastapi.responses import FileResponse, JSONResponse, PlainTextResponse
from sqlalchemy.orm import Session

from app.database import get_db, now
from app.models import Document, Folder, ShareLink, User
from app.permissions import has_permission
from app.security import get_current_user, get_optional_user, verify_password

webdav = APIRouter(prefix="/webdav", tags=["webdav"])
cmis = APIRouter(prefix="/cmis", tags=["cmis"])
soap = APIRouter(prefix="/soap", tags=["soap"])
_basic = HTTPBasic(auto_error=False)


def _dav_user(
    request: Request,
    creds: HTTPBasicCredentials | None = Depends(_basic),
    db: Session = Depends(get_db),
    user: User | None = Depends(get_optional_user),
) -> User:
    if user:
        return user
    # Check token in query param (?token=...) or Header (X-Share-Token / Authorization)
    token = request.query_params.get("token") or request.headers.get("X-Share-Token")
    if token:
        share = db.query(ShareLink).filter(ShareLink.token == token).first()
        if share and (not share.expires_at or share.expires_at > now()):
            creator = db.get(User, share.created_by)
            if creator and creator.is_active:
                return creator
    if creds:
        u = db.query(User).filter(User.username == creds.username).first()
        if u and u.is_active and verify_password(creds.password, u.hashed_password):
            return u
    raise HTTPException(401, "Not authenticated", headers={"WWW-Authenticate": 'Basic realm="NewtonEDMS"'})

NS = {"D": "DAV:"}


def _root(db: Session) -> Folder:
    return db.query(Folder).filter(Folder.parent_id.is_(None)).first()


def _resolve(db: Session, path: str) -> tuple[Folder | None, Document | None]:
    parts = [p for p in unquote(path).strip("/").split("/") if p]
    folder = _root(db)
    if not parts:
        return folder, None
    for i, part in enumerate(parts):
        child = (
            db.query(Folder)
            .filter(Folder.parent_id == folder.id, Folder.name == part, Folder.deleted_at.is_(None))
            .first()
        )
        if child:
            folder = child
            continue
        if i == len(parts) - 1:
            doc = (
                db.query(Document)
                .filter(Document.folder_id == folder.id, Document.name == part, Document.deleted_at.is_(None))
                .first()
            )
            return folder, doc
        return None, None
    return folder, None


from datetime import datetime, timedelta
import secrets
import uuid

_locks: dict[str, dict] = {}


def _lock_key(path: str) -> str:
    return "/" + path.strip("/")


def _active_lock(path: str) -> dict | None:
    row = _locks.get(_lock_key(path))
    if not row:
        return None
    if row.get("expires") and row["expires"] < datetime.utcnow():
        _locks.pop(_lock_key(path), None)
        return None
    return row


@webdav.options("/{path:path}")
async def webdav_options(path: str = ""):
    return Response(
        headers={
            "Allow": "OPTIONS, GET, PUT, DELETE, PROPFIND, MKCOL, MOVE, COPY, HEAD, LOCK, UNLOCK",
            "DAV": "1,2",
            "Lock-Token": "opaquelocktoken:newton",
        }
    )


@webdav.api_route("/{path:path}", methods=["PROPFIND", "GET", "PUT", "DELETE", "MKCOL", "MOVE", "COPY", "HEAD", "LOCK", "UNLOCK"])
async def webdav_dispatch(path: str, request: Request, db: Session = Depends(get_db), user: User = Depends(_dav_user)):
    folder, doc = _resolve(db, path)
    method = request.method.upper()
    if method in ("GET", "HEAD"):
        if not doc or not doc.file_path or not Path(doc.file_path).exists():
            raise HTTPException(404)
        if not has_permission(db, user, "read", folder, doc):
            raise HTTPException(403)
        return FileResponse(doc.file_path, filename=doc.name)
    if method == "PROPFIND":
        href = "/webdav/" + path.strip("/")
        if doc:
            body = _prop_response(href, doc.name, False, doc.size or 0)
        elif folder:
            items = [_prop_response(href, folder.name, True, 0)]
            for ch in db.query(Folder).filter(Folder.parent_id == folder.id, Folder.deleted_at.is_(None)).all():
                items.append(_prop_response(f"{href.rstrip('/')}/{ch.name}", ch.name, True, 0))
            for d in db.query(Document).filter(Document.folder_id == folder.id, Document.deleted_at.is_(None)).all():
                items.append(_prop_response(f"{href.rstrip('/')}/{d.name}", d.name, False, d.size or 0))
            body = '<?xml version="1.0"?><D:multistatus xmlns:D="DAV:">' + "".join(items) + "</D:multistatus>"
        else:
            raise HTTPException(404)
        return Response(content=body, media_type="application/xml", status_code=207)
    if method == "MKCOL":
        parent_path = "/".join(path.strip("/").split("/")[:-1])
        name = path.strip("/").split("/")[-1]
        parent, _ = _resolve(db, parent_path)
        if not parent:
            raise HTTPException(409)
        if not has_permission(db, user, "write", parent):
            raise HTTPException(403)
        db.add(Folder(name=name, parent_id=parent.id, created_by=user.id, is_public=False, collective_id=getattr(parent, "collective_id", None) or user.collective_id))
        db.commit()
        return Response(status_code=201)
    if method == "PUT":
        parent_path = "/".join(path.strip("/").split("/")[:-1])
        name = path.strip("/").split("/")[-1]
        parent, existing = _resolve(db, path)
        data = await request.body()
        from app.joex import schedule_document
        from app.storage import doc_storage_dir, safe_filename

        target_folder = parent
        if existing:
            target_folder = db.get(Folder, existing.folder_id)
        if not target_folder:
            parent, _ = _resolve(db, parent_path)
            target_folder = parent
        if not target_folder or not has_permission(db, user, "write", target_folder):
            raise HTTPException(403)
        if not existing:
            existing = Document(name=name, title=name, folder_id=target_folder.id, current_version=1, status="draft", size=len(data), file_path="", created_by=user.id, source="webdav", collective_id=getattr(target_folder, "collective_id", None) or user.collective_id)
            db.add(existing)
            db.commit()
            db.refresh(existing)
        dest = doc_storage_dir(existing.id)
        dest.mkdir(parents=True, exist_ok=True)
        fp = dest / safe_filename(name)
        fp.write_bytes(data)
        existing.file_path = str(fp)
        existing.size = len(data)
        db.commit()
        schedule_document(db, existing.id, created_by=user.id)
        return Response(status_code=201)
    if method == "DELETE":
        if doc:
            if not has_permission(db, user, "delete", folder, doc):
                raise HTTPException(403)
            from app.database import now as utcnow

            doc.deleted_at = utcnow()
            doc.deleted_by = user.id
            db.commit()
            return Response(status_code=204)
        if folder and folder.parent_id:
            if not has_permission(db, user, "delete", folder):
                raise HTTPException(403)
            from app.database import now as utcnow

            folder.deleted_at = utcnow()
            folder.deleted_by = user.id
            db.commit()
            return Response(status_code=204)
        raise HTTPException(404)
    if method == "LOCK":
        token = "opaquelocktoken:" + secrets.token_hex(8)
        timeout = datetime.utcnow() + timedelta(hours=1)
        _locks[_lock_key(path)] = {"token": token, "owner": user.username, "expires": timeout}
        body = (
            f'<?xml version="1.0"?><D:prop xmlns:D="DAV:"><D:lockdiscovery><D:activelock>'
            f"<D:locktoken><D:href>{token}</D:href></D:locktoken>"
            f"<D:timeout>Second-3600</D:timeout></D:activelock></D:lockdiscovery></D:prop>"
        )
        return Response(content=body, media_type="application/xml", status_code=200, headers={"Lock-Token": f"<{token}>"})
    if method == "UNLOCK":
        token = (request.headers.get("Lock-Token") or "").strip("<> ")
        row = _active_lock(path)
        if not row:
            return Response(status_code=204)
        if token and row.get("token") != token and user.role not in ("superadmin", "admin"):
            raise HTTPException(403, "Lock token mismatch")
        _locks.pop(_lock_key(path), None)
        return Response(status_code=204)
    if method in ("MOVE", "COPY"):
        dest = request.headers.get("Destination") or ""
        dest_path = dest.split("/webdav/", 1)[-1] if "/webdav/" in dest else dest
        dest_path = dest_path.split("?")[0]
        parent_path = "/".join(dest_path.strip("/").split("/")[:-1])
        new_name = dest_path.strip("/").split("/")[-1]
        dest_folder, dest_doc = _resolve(db, dest_path)
        src_folder, src_doc = folder, doc
        parent, _ = _resolve(db, parent_path)
        if not parent:
            raise HTTPException(409, "Destination parent missing")
        if not has_permission(db, user, "write", parent):
            raise HTTPException(403)
        if src_doc:
            if method == "MOVE":
                src_doc.folder_id = parent.id
                src_doc.name = new_name or src_doc.name
                db.commit()
                return Response(status_code=201)
            from app.storage import doc_storage_dir, safe_filename
            from pathlib import Path as P

            clone = Document(
                name=new_name or src_doc.name,
                title=src_doc.title,
                folder_id=parent.id,
                current_version=1,
                status=src_doc.status,
                size=src_doc.size,
                mime=src_doc.mime,
                file_path="",
                created_by=user.id,
                source="webdav",
                collective_id=getattr(parent, "collective_id", None) or getattr(user, "collective_id", None),
            )
            db.add(clone)
            db.commit()
            db.refresh(clone)
            if src_doc.file_path and P(src_doc.file_path).exists():
                dest_dir = doc_storage_dir(clone.id)
                dest_dir.mkdir(parents=True, exist_ok=True)
                fp = dest_dir / safe_filename(clone.name)
                fp.write_bytes(P(src_doc.file_path).read_bytes())
                clone.file_path = str(fp)
                db.commit()
            return Response(status_code=201)
        if src_folder and src_folder.parent_id:
            if method == "MOVE":
                src_folder.parent_id = parent.id
                src_folder.name = new_name or src_folder.name
                db.commit()
                return Response(status_code=201)
            nf = Folder(
                name=new_name or src_folder.name,
                parent_id=parent.id,
                created_by=user.id,
                is_public=False,
                collective_id=getattr(parent, "collective_id", None) or getattr(user, "collective_id", None),
            )
            db.add(nf)
            db.commit()
            return Response(status_code=201)
        raise HTTPException(404)
    return Response(status_code=405)


def _prop_response(href: str, name: str, is_dir: bool, size: int) -> str:
    t = "httpd/unix-directory" if is_dir else "application/octet-stream"
    extra = "<D:resourcetype><D:collection/></D:resourcetype>" if is_dir else f"<D:resourcetype/><D:getcontentlength>{size}</D:getcontentlength>"
    return f"<D:response><D:href>{href}</D:href><D:propstat><D:prop><D:displayname>{name}</D:displayname><D:getcontenttype>{t}</D:getcontenttype>{extra}</D:prop><D:status>HTTP/1.1 200 OK</D:status></D:propstat></D:response>"


@cmis.get("/browser")
def cmis_repo(user: User = Depends(get_current_user)):
    return {
        "newton": {
            "repositoryId": "newton",
            "repositoryName": "NewtonEDMS",
            "repositoryDescription": "CMIS browser binding",
            "productName": "NewtonEDMS",
            "productVersion": "1.0.0",
            "rootFolderId": "folder-root",
            "capabilities": {"capabilityQuery": "metadataonly", "capabilityACL": "manage"},
        }
    }


@cmis.get("/browser/root")
def cmis_root(db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    root = _root(db)
    children = []
    for f in db.query(Folder).filter(Folder.parent_id == root.id, Folder.deleted_at.is_(None)).all():
        children.append({"objectId": f"folder-{f.id}", "baseTypeId": "cmis:folder", "name": f.name})
    for d in db.query(Document).filter(Document.folder_id == root.id, Document.deleted_at.is_(None)).limit(100).all():
        children.append({"objectId": f"doc-{d.id}", "baseTypeId": "cmis:document", "name": d.name})
    return {"objects": children, "hasMoreItems": False, "numItems": len(children)}


@cmis.get("/browser/object")
def cmis_object(id: str, db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    if id.startswith("folder-"):
        fid = id.replace("folder-", "")
        if fid == "root":
            f = _root(db)
        else:
            f = db.get(Folder, int(fid))
        if not f:
            raise HTTPException(404)
        children = []
        for ch in db.query(Folder).filter(Folder.parent_id == f.id, Folder.deleted_at.is_(None)).all():
            children.append({"objectId": f"folder-{ch.id}", "baseTypeId": "cmis:folder", "name": ch.name})
        for d in db.query(Document).filter(Document.folder_id == f.id, Document.deleted_at.is_(None)).limit(200).all():
            children.append({"objectId": f"doc-{d.id}", "baseTypeId": "cmis:document", "name": d.name})
        return {
            "objectId": f"folder-{f.id}",
            "baseTypeId": "cmis:folder",
            "name": f.name,
            "parentId": f.parent_id,
            "objects": children,
            "numItems": len(children),
        }
    if id.startswith("doc-"):
        d = db.get(Document, int(id.replace("doc-", "")))
        if not d:
            raise HTTPException(404)
        return {"objectId": f"doc-{d.id}", "baseTypeId": "cmis:document", "name": d.name, "contentStreamLength": d.size}
    raise HTTPException(404)


@cmis.post("/browser/root")
@cmis.post("/browser/object")
async def cmis_write(request: Request, id: str | None = None, db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    form = dict((await request.form()).items()) if request.headers.get("content-type", "").startswith("multipart") or "x-www-form-urlencoded" in (request.headers.get("content-type") or "") else {}
    if not form:
        try:
            body = await request.json()
            form = body if isinstance(body, dict) else {}
        except Exception:
            form = dict(request.query_params)
    action = (form.get("cmisaction") or form.get("action") or request.query_params.get("cmisaction") or "").lower()
    object_id = id or form.get("objectId") or request.query_params.get("id") or "folder-root"

    if action in ("createdocument", "create"):
        folder = _root(db)
        if str(object_id).startswith("folder-") and str(object_id) != "folder-root":
            folder = db.get(Folder, int(str(object_id).replace("folder-", ""))) or folder
        if not has_permission(db, user, "write", folder):
            raise HTTPException(403)
        name = form.get("name") or form.get("cmis:name") or "untitled.bin"
        content = form.get("content") or form.get("file") or ""
        data = content.encode() if isinstance(content, str) else b""
        from app.storage import doc_storage_dir, safe_filename

        d = Document(
            name=str(name),
            title=str(name),
            folder_id=folder.id,
            current_version=1,
            status="draft",
            size=len(data),
            file_path="",
            created_by=user.id,
            source="cmis",
            collective_id=getattr(folder, "collective_id", None) or user.collective_id,
        )
        db.add(d)
        db.commit()
        db.refresh(d)
        dest = doc_storage_dir(d.id)
        dest.mkdir(parents=True, exist_ok=True)
        fp = dest / safe_filename(str(name))
        fp.write_bytes(data)
        d.file_path = str(fp)
        db.commit()
        return JSONResponse({"objectId": f"doc-{d.id}", "name": d.name}, status_code=201)

    if action in ("createfolder", "mkcol"):
        parent = _root(db)
        if str(object_id).startswith("folder-") and str(object_id) != "folder-root":
            parent = db.get(Folder, int(str(object_id).replace("folder-", ""))) or parent
        if not has_permission(db, user, "write", parent):
            raise HTTPException(403)
        name = form.get("name") or "folder"
        f = Folder(name=str(name), parent_id=parent.id, created_by=user.id, is_public=False, collective_id=getattr(parent, "collective_id", None) or user.collective_id)
        db.add(f)
        db.commit()
        db.refresh(f)
        return JSONResponse({"objectId": f"folder-{f.id}", "name": f.name}, status_code=201)

    if action in ("update", "updateproperties"):
        if str(object_id).startswith("doc-"):
            d = db.get(Document, int(str(object_id).replace("doc-", "")))
            if not d:
                raise HTTPException(404)
            f = db.get(Folder, d.folder_id)
            if not has_permission(db, user, "write", f, d):
                raise HTTPException(403)
            if form.get("name"):
                d.name = str(form.get("name"))
                d.title = d.name
            db.commit()
            return {"objectId": f"doc-{d.id}", "name": d.name}
        raise HTTPException(400, "update requires a document objectId")

    if action in ("delete", "deleteobject"):
        if str(object_id).startswith("doc-"):
            d = db.get(Document, int(str(object_id).replace("doc-", "")))
            if not d:
                raise HTTPException(404)
            f = db.get(Folder, d.folder_id)
            if not has_permission(db, user, "delete", f, d):
                raise HTTPException(403)
            from app.database import now as utcnow

            d.deleted_at = utcnow()
            d.deleted_by = user.id
            db.commit()
            return {"ok": True}
        raise HTTPException(400, "delete requires a document objectId")
    raise HTTPException(400, f"Unsupported cmisaction: {action or '(missing)'}")


@soap.post("/{service}")
async def soap_dispatch(service: str, request: Request, db: Session = Depends(get_db), user: User | None = Depends(get_optional_user)):
    raw = (await request.body()).decode("utf-8", errors="ignore")
    try:
        root = ET.fromstring(raw)
    except ET.ParseError:
        return PlainTextResponse("Invalid SOAP", status_code=400)
    body = None
    for el in root.iter():
        if el.tag.lower().endswith("body"):
            body = el
            break
    method = list(body)[0] if body is not None and list(body) else None
    name = (method.tag.split("}")[-1] if method is not None else "unknown")
    args = {c.tag.split("}")[-1]: (c.text or "") for c in list(method or [])}

    def envelope(inner: str) -> Response:
        xml = f'<?xml version="1.0"?><soap:Envelope xmlns:soap="http://schemas.xmlsoap.org/soap/envelope/"><soap:Body>{inner}</soap:Body></soap:Envelope>'
        return Response(content=xml, media_type="text/xml")

    svc = service.lower()
    if svc == "auth" and name.lower() in ("login", "authenticate"):
        u = db.query(User).filter(User.username == args.get("username") or args.get("user")).first()
        if not u or not verify_password(args.get("password") or "", u.hashed_password):
            return envelope("<fault><faultstring>Invalid credentials</faultstring></fault>")
        from app.security import create_access_token

        token = create_access_token({"sub": u.username, "role": u.role})
        return envelope(f"<loginResponse><sid>{token}</sid></loginResponse>")
    if not user:
        raise HTTPException(401, "Not authenticated")
    if svc == "folder" and name.lower() == "list":
        folders = db.query(Folder).filter(Folder.deleted_at.is_(None)).limit(100).all()
        items = "".join(f"<folder><id>{f.id}</id><name>{f.name}</name></folder>" for f in folders)
        return envelope(f"<listResponse>{items}</listResponse>")
    if svc == "document" and name.lower() in ("list", "listbyfolder"):
        fid = args.get("folderId") or args.get("folder_id")
        q = db.query(Document).filter(Document.deleted_at.is_(None))
        if fid:
            q = q.filter(Document.folder_id == int(fid))
        docs = q.limit(100).all()
        items = "".join(f"<document><id>{d.id}</id><name>{d.name}</name></document>" for d in docs)
        return envelope(f"<listResponse>{items}</listResponse>")
    if svc == "document" and name.lower() in ("get", "getdocument"):
        did = int(args.get("id") or args.get("documentId") or 0)
        d = db.get(Document, did)
        if not d:
            return envelope("<fault><faultstring>Not found</faultstring></fault>")
        return envelope(
            f"<getDocumentResponse><id>{d.id}</id><title>{d.title}</title>"
            f"<status>{d.status}</status><tags>{d.tags or ''}</tags></getDocumentResponse>"
        )
    if svc == "document" and name.lower() in ("create", "createdocument"):
        fid = int(args.get("folderId") or args.get("folder_id") or 0)
        folder = db.get(Folder, fid) if fid else _root(db)
        if not folder or not has_permission(db, user, "write", folder):
            return envelope("<fault><faultstring>No permission</faultstring></fault>")
        title = args.get("title") or args.get("name") or "untitled"
        content_b64 = args.get("content") or args.get("data") or ""
        import base64

        data = base64.b64decode(content_b64) if content_b64 else b""
        from app.storage import doc_storage_dir, safe_filename

        d = Document(
            name=title,
            title=title,
            folder_id=folder.id,
            current_version=1,
            status="draft",
            size=len(data),
            file_path="",
            created_by=user.id,
            source="soap",
            tags=args.get("tags") or "",
            collective_id=getattr(folder, "collective_id", None) or user.collective_id,
        )
        db.add(d)
        db.commit()
        db.refresh(d)
        dest = doc_storage_dir(d.id)
        dest.mkdir(parents=True, exist_ok=True)
        fp = dest / safe_filename(title)
        fp.write_bytes(data)
        d.file_path = str(fp)
        db.commit()
        return envelope(f"<createDocumentResponse><id>{d.id}</id></createDocumentResponse>")
    if svc == "document" and name.lower() in ("download", "getcontent"):
        did = int(args.get("id") or args.get("documentId") or 0)
        d = db.get(Document, did)
        if not d or not d.file_path:
            return envelope("<fault><faultstring>Not found</faultstring></fault>")
        import base64
        from pathlib import Path as P

        raw = P(d.file_path).read_bytes() if P(d.file_path).exists() else b""
        return envelope(
            f"<downloadResponse><id>{d.id}</id><name>{d.name}</name>"
            f"<content>{base64.b64encode(raw).decode()}</content></downloadResponse>"
        )
    if svc == "document" and name.lower() in ("checkout", "checkoutdocument"):
        did = int(args.get("id") or args.get("documentId") or 0)
        d = db.get(Document, did)
        if not d:
            return envelope("<fault><faultstring>Not found</faultstring></fault>")
        d.checked_out_by = user.id
        db.commit()
        return envelope(f"<checkoutResponse><id>{d.id}</id><checkedOutBy>{user.id}</checkedOutBy></checkoutResponse>")
    if svc == "document" and name.lower() in ("checkin", "checkindocument"):
        did = int(args.get("id") or args.get("documentId") or 0)
        d = db.get(Document, did)
        if not d:
            return envelope("<fault><faultstring>Not found</faultstring></fault>")
        d.checked_out_by = None
        db.commit()
        return envelope(f"<checkinResponse><id>{d.id}</id></checkinResponse>")
    if svc == "document" and name.lower() in ("update", "updatedocument"):
        did = int(args.get("id") or 0)
        d = db.get(Document, did)
        if not d:
            return envelope("<fault><faultstring>Not found</faultstring></fault>")
        if args.get("title"):
            d.title = args["title"]
        if args.get("tags") is not None:
            d.tags = args.get("tags")
        db.commit()
        return envelope(f"<updateDocumentResponse><id>{d.id}</id></updateDocumentResponse>")
    if svc == "search":
        q = args.get("query") or ""
        docs = db.query(Document).filter(Document.deleted_at.is_(None), Document.title.ilike(f"%{q}%")).limit(50).all()
        items = "".join(f"<hit><id>{d.id}</id><title>{d.title}</title></hit>" for d in docs)
        return envelope(f"<searchResponse>{items}</searchResponse>")
    if svc == "system":
        return envelope("<info><product>NewtonEDMS</product><version>1.0.0</version></info>")
    return envelope(f"<ok><service>{service}</service><method>{name}</method></ok>")
