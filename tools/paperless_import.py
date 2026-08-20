#!/usr/bin/env python3
"""Import a Paperless-ngx document export into NewtonEDMS.

Expects a folder of files plus optional ``metadata.json`` (list of objects with
``title``, ``tags``, ``correspondent``, ``created``, ``filename``).
Falls back to uploading every file found if no metadata is present.
"""
from __future__ import annotations

import argparse
import json
import mimetypes
from pathlib import Path

import httpx


def main() -> int:
    p = argparse.ArgumentParser(description="Paperless → NewtonEDMS import")
    p.add_argument("source", type=Path, help="export directory")
    p.add_argument("--url", default="http://127.0.0.1:8000")
    p.add_argument("--user", default="admin")
    p.add_argument("--password", default="admin123")
    p.add_argument("--folder", type=int, default=None)
    args = p.parse_args()
    client = httpx.Client(base_url=args.url, timeout=120.0, follow_redirects=True)
    r = client.post("/api/auth/login", data={"username": args.user, "password": args.password})
    r.raise_for_status()
    folder_id = args.folder
    if folder_id is None:
        folders = client.get("/api/folders/all").json()
        folder_id = next(f["id"] for f in folders if f.get("parent_id") is None)
    meta_path = args.source / "metadata.json"
    items = []
    if meta_path.exists():
        items = json.loads(meta_path.read_text(encoding="utf-8"))
        if isinstance(items, dict):
            items = items.get("documents") or items.get("items") or []
    else:
        for f in sorted(args.source.rglob("*")):
            if f.is_file() and f.name != "metadata.json":
                items.append({"filename": str(f.relative_to(args.source)), "title": f.stem})
    n = 0
    for item in items:
        rel = item.get("filename") or item.get("original_file") or item.get("path")
        if not rel:
            continue
        path = args.source / rel
        if not path.exists():
            # paperless often stores originals in archive/
            alt = args.source / "originals" / Path(rel).name
            path = alt if alt.exists() else path
        if not path.exists():
            print(f"skip missing {rel}")
            continue
        tags = item.get("tags") or []
        if isinstance(tags, list):
            tags = ",".join(str(t) if not isinstance(t, dict) else t.get("name", "") for t in tags)
        with path.open("rb") as fh:
            mime = mimetypes.guess_type(path.name)[0] or "application/octet-stream"
            resp = client.post(
                "/api/documents",
                data={
                    "folder_id": str(folder_id),
                    "title": item.get("title") or path.stem,
                    "tags": tags or "",
                },
                files={"file": (path.name, fh, mime)},
            )
        if resp.status_code >= 400:
            print(f"fail {path.name}: {resp.text}")
            continue
        doc_id = resp.json()["id"]
        extra = {}
        if item.get("created"):
            extra["item_date"] = str(item["created"])[:10]
        if extra:
            client.put(f"/api/documents/{doc_id}", data=extra)
        n += 1
        print(f"imported {path.name} -> #{doc_id}")
    print(f"done, {n} file(s)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
