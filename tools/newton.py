#!/usr/bin/env python3
"""NewtonEDMS command-line client: watch folders, upload, search.

Usage::

    python tools/newton.py --url http://localhost:8000 --user admin --password admin123 search 'tag:invoice'
    python tools/newton.py --url http://localhost:8000 --token SOURCE_TOKEN upload ./file.pdf
    python tools/newton.py watch ./inbox --token SOURCE_TOKEN --url http://localhost:8000
"""
from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path

try:
    import httpx
except ImportError:
    print("httpx is required: pip install httpx", file=sys.stderr)
    sys.exit(1)


def login(base: str, user: str, password: str) -> httpx.Client:
    client = httpx.Client(base_url=base, timeout=60.0, follow_redirects=True)
    r = client.post("/api/auth/login", data={"username": user, "password": password})
    r.raise_for_status()
    return client


def cmd_search(client: httpx.Client, query: str) -> None:
    r = client.get("/api/query", params={"q": query})
    r.raise_for_status()
    for d in r.json():
        print(f"{d['id']}\t{d.get('title') or d.get('name')}\t{d.get('tags')}")


def cmd_upload(client: httpx.Client, path: Path, folder_id: int | None, token: str | None) -> None:
    if token:
        with path.open("rb") as fh:
            r = client.post(f"/api/v1/open/upload/item/{token}", files={"file": (path.name, fh)})
        r.raise_for_status()
        print(r.text)
        return
    if folder_id is None:
        folders = client.get("/api/folders/all").json()
        folder_id = next(f["id"] for f in folders if f.get("parent_id") is None)
    with path.open("rb") as fh:
        r = client.post(
            "/api/documents",
            data={"folder_id": str(folder_id), "title": path.name},
            files={"file": (path.name, fh)},
        )
    r.raise_for_status()
    print(json.dumps(r.json(), indent=2))


def cmd_watch(base: str, folder: Path, token: str, poll: float) -> None:
    seen: set[str] = set()
    client = httpx.Client(base_url=base, timeout=60.0)
    print(f"watching {folder} → {base}")
    while True:
        for p in folder.iterdir():
            if not p.is_file() or p.name.startswith("."):
                continue
            key = f"{p.name}:{p.stat().st_mtime}"
            if key in seen:
                continue
            try:
                cmd_upload(client, p, None, token)
                seen.add(key)
            except Exception as exc:
                print(f"upload failed {p}: {exc}", file=sys.stderr)
        time.sleep(poll)


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(prog="newton", description="NewtonEDMS CLI")
    p.add_argument("--url", default="http://127.0.0.1:8000")
    p.add_argument("--user", default="admin")
    p.add_argument("--password", default="admin123")
    p.add_argument("--token", help="anonymous source token")
    sub = p.add_subparsers(dest="cmd", required=True)
    s = sub.add_parser("search")
    s.add_argument("query")
    u = sub.add_parser("upload")
    u.add_argument("path")
    u.add_argument("--folder", type=int, default=None)
    w = sub.add_parser("watch")
    w.add_argument("folder")
    w.add_argument("--poll", type=float, default=5.0)
    args = p.parse_args(argv)
    if args.cmd == "watch":
        if not args.token:
            p.error("watch requires --token")
        cmd_watch(args.url, Path(args.folder), args.token, args.poll)
        return 0
    client = httpx.Client(base_url=args.url, timeout=60.0) if args.token else login(args.url, args.user, args.password)
    if args.cmd == "search":
        cmd_search(client, args.query)
    elif args.cmd == "upload":
        cmd_upload(client, Path(args.path), args.folder, args.token)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
