"""Run packaged addons (zip + YAML descriptor) and apply stdout instructions."""
from __future__ import annotations

import json
import logging
import shutil
import subprocess
import tempfile
import zipfile
from pathlib import Path

from app.models import Addon, Document, DocumentAttachment, Tag
from app.storage import doc_storage_dir, safe_filename

logger = logging.getLogger("newtonedms.addons")


def install_zip(db, user_id: int, zip_path: Path, name: str | None = None) -> Addon:
    dest_root = Path(tempfile.gettempdir()) if False else None
    from app import database

    dest = database.STORAGE_DIR / "addons" / safe_filename(zip_path.stem)
    dest.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(zip_path) as zf:
        zf.extractall(dest)
    descriptor = _load_descriptor(dest)
    addon = Addon(
        name=name or descriptor.get("name") or zip_path.stem,
        event=descriptor.get("trigger") or descriptor.get("event") or "on_process",
        webhook_url=descriptor.get("webhook") or "",
        enabled=True,
        created_by=user_id,
        package_path=str(dest),
        descriptor=descriptor,
        trigger=descriptor.get("trigger") or "on_process",
        sandbox=descriptor.get("sandbox") or "subprocess",
    )
    db.add(addon)
    db.commit()
    db.refresh(addon)
    return addon


def _load_descriptor(root: Path) -> dict:
    for cand in ("addon.yaml", "addon.yml", "docspell-addon.yml", "newton-addon.yaml"):
        p = root / cand
        if p.exists():
            import yaml

            data = yaml.safe_load(p.read_text(encoding="utf-8")) or {}
            if isinstance(data, dict):
                return data
    nested = list(root.glob("*/addon.yaml")) + list(root.glob("*/addon.yml"))
    if nested:
        import yaml

        return yaml.safe_load(nested[0].read_text(encoding="utf-8")) or {}
    # Infer a runnable program
    for prog in ("run.sh", "run.py", "addon.py", "main.py"):
        hit = next(root.rglob(prog), None)
        if hit:
            return {"name": root.name, "program": str(hit.relative_to(root)), "trigger": "on_process"}
    return {"name": root.name, "trigger": "on_process"}


def run_addon(db, addon: Addon, doc: Document, *, extra_env: dict | None = None) -> dict:
    """Execute the addon against ``doc`` and apply JSON instructions from stdout."""
    if addon.webhook_url and not addon.package_path:
        from app.joex import _fire_addons

        _fire_addons(db, addon.event or "on_process", doc)
        return {"ok": True, "via": "webhook"}
    root = Path(addon.package_path or "")
    desc = dict(addon.descriptor or {})
    program = desc.get("program") or desc.get("cmd") or ""
    if not program:
        for cand in ("run.py", "run.sh", "addon.py"):
            if (root / cand).exists():
                program = cand
                break
    if not program:
        return {"ok": False, "error": "no program in descriptor"}
    work = Path(tempfile.mkdtemp(prefix="newton-addon-"))
    item_json = work / "item.json"
    item_json.write_text(
        json.dumps(
            {
                "id": doc.id,
                "title": doc.title,
                "name": doc.name,
                "tags": [t for t in (doc.tags or "").split(",") if t.strip()],
                "notes": doc.notes,
                "extracted_text": (doc.extracted_text or "")[:20_000],
                "language": doc.language,
                "file": doc.file_path,
            }
        ),
        encoding="utf-8",
    )
    cmd = _sandbox_cmd(addon.sandbox or "subprocess", root, program, work, desc)
    env = {**dict(**{k: str(v) for k, v in __import__("os").environ.items()}), **(extra_env or {})}
    env["ITEM_JSON"] = str(item_json)
    env["ITEM_FILE"] = doc.file_path or ""
    try:
        proc = subprocess.run(
            cmd,
            cwd=str(root if root.exists() else work),
            capture_output=True,
            text=True,
            timeout=int(desc.get("timeout") or 60),
            env=env,
            check=False,
        )
    except Exception as exc:
        logger.exception("addon %s failed", addon.name)
        shutil.rmtree(work, ignore_errors=True)
        return {"ok": False, "error": str(exc)}
    stdout = proc.stdout or ""
    applied = apply_instructions(db, doc, stdout)
    shutil.rmtree(work, ignore_errors=True)
    return {
        "ok": proc.returncode == 0,
        "returncode": proc.returncode,
        "stdout": stdout[:8000],
        "stderr": (proc.stderr or "")[:2000],
        "applied": applied,
    }


def _sandbox_cmd(sandbox: str, root: Path, program: str, work: Path, desc: dict) -> list[str]:
    prog_path = Path(program)
    if not prog_path.is_absolute():
        prog_path = root / program
    args = [str(a) for a in (desc.get("args") or [])]
    if sandbox == "docker" and shutil.which("docker"):
        image = desc.get("image") or "python:3.12-slim"
        return [
            "docker",
            "run",
            "--rm",
            "-v",
            f"{root}:/addon:ro",
            "-v",
            f"{work}:/work",
            "-e",
            "ITEM_JSON=/work/item.json",
            image,
            "python" if prog_path.suffix == ".py" else "sh",
            f"/addon/{program}",
            *args,
        ]
    if sandbox == "nix" and shutil.which("nix"):
        return ["nix", "shell", "--command", str(prog_path), *args]
    if prog_path.suffix == ".py":
        import sys

        return [sys.executable, str(prog_path), *args]
    return [str(prog_path), *args]


def apply_instructions(db, doc: Document, stdout: str) -> list[str]:
    """Parse JSON object/array from stdout and mutate the item.

    Supported keys: tags, notes, title, language, metadata, fields, files.
    """
    raw = stdout.strip()
    if not raw:
        return []
    data = None
    try:
        data = json.loads(raw)
    except json.JSONDecodeError:
        start = raw.find("{")
        end = raw.rfind("}")
        if start >= 0 and end > start:
            try:
                data = json.loads(raw[start : end + 1])
            except json.JSONDecodeError:
                data = None
    if data is None:
        # Treat leftover stdout as a note append
        if raw:
            doc.notes = ((doc.notes or "") + "\n" + raw[:4000]).strip()
            db.commit()
            return ["notes"]
        return []
    if isinstance(data, list):
        applied = []
        for item in data:
            if isinstance(item, dict):
                applied.extend(apply_instructions(db, doc, json.dumps(item)))
        return applied
    applied: list[str] = []
    if tags := data.get("tags"):
        existing = {t.strip() for t in (doc.tags or "").split(",") if t.strip()}
        if isinstance(tags, str):
            tags = [t.strip() for t in tags.split(",") if t.strip()]
        existing |= {str(t).strip() for t in tags if str(t).strip()}
        doc.tags = ",".join(sorted(existing))
        for t in tags:
            name = str(t).strip()
            if name and not db.query(Tag).filter(Tag.name == name).first():
                db.add(Tag(name=name, created_by=doc.created_by))
        applied.append("tags")
    if "notes" in data and data["notes"] is not None:
        doc.notes = str(data["notes"])
        applied.append("notes")
    if data.get("title"):
        doc.title = str(data["title"])
        applied.append("title")
    if data.get("language"):
        doc.language = str(data["language"])
        applied.append("language")
    if isinstance(data.get("metadata"), dict):
        meta = dict(doc.metadata_json or {})
        meta.update(data["metadata"])
        doc.metadata_json = meta
        applied.append("metadata")
    dest = doc_storage_dir(doc.id) / "addon"
    dest.mkdir(parents=True, exist_ok=True)
    for fdesc in data.get("files") or []:
        if not isinstance(fdesc, dict):
            continue
        name = safe_filename(fdesc.get("name") or "addon.bin")
        content = fdesc.get("content") or fdesc.get("text") or ""
        target = dest / name
        if fdesc.get("base64"):
            import base64

            target.write_bytes(base64.b64decode(fdesc["base64"]))
        else:
            target.write_text(str(content), encoding="utf-8")
        db.add(
            DocumentAttachment(
                document_id=doc.id,
                name=name,
                file_path=str(target),
                size=target.stat().st_size,
                mime=fdesc.get("mime"),
                role="extracted",
            )
        )
        applied.append("files")
    db.commit()
    return applied


def run_for_event(db, event: str, doc: Document) -> None:
    addons = (
        db.query(Addon)
        .filter(Addon.enabled.is_(True))
        .filter((Addon.trigger == event) | (Addon.event == event))
        .all()
    )
    for addon in addons:
        try:
            run_addon(db, addon, doc)
        except Exception:
            logger.exception("addon %s event %s failed", addon.name, event)
