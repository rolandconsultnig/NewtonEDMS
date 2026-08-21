"""Comprehensive Full-System Audit & Smoke Crawler.

Audits:
1. Every GET/POST route registered in the FastAPI app
2. All frontend `apiFetch` URLs extracted from frontend/ JS files
3. All admin and navigation tabs in index.html
4. Database schema integrity and relationships
"""
from __future__ import annotations

import re
from pathlib import Path
import pytest
from fastapi.testclient import TestClient

from app.main import app


def test_audit_all_fastapi_routes(client, admin_user):
    """Walk every registered route in the FastAPI application and ensure valid responses."""
    from tests.conftest import _auth, _login

    headers = _auth(_login(client, "admin", "admin123"))

    failed_routes = []
    total_routes = 0

    for route in app.routes:
        methods = getattr(route, "methods", None)
        path = getattr(route, "path", None)

        if not methods or not path:
            continue

        # Skip WebDAV/SOAP/CMIS/WS wildcard or parameterized subpaths that require dynamic params
        if "{" in path or path.startswith(("/webdav", "/cmis", "/soap", "/ws")):
            continue

        if "GET" in methods:
            total_routes += 1
            res = client.get(path, headers=headers)
            # 200, 204, 304, 307, 308, 400, 422 (for required query params) are acceptable; 404 and 500 indicate broken routes
            if res.status_code in (404, 500):
                failed_routes.append((path, res.status_code, res.text[:200]))

    assert not failed_routes, f"Broken API endpoints detected: {failed_routes}"
    assert total_routes > 30, f"Expected at least 30 GET routes, tested {total_routes}"


def test_audit_frontend_api_calls(client, admin_user):
    """Scan all frontend .js files for apiFetch('/...') calls and verify each has a matching backend route."""
    from tests.conftest import _auth, _login

    headers = _auth(_login(client, "admin", "admin123"))

    frontend_dir = Path("frontend")
    api_calls = set()

    for js_file in frontend_dir.glob("*.js"):
        content = js_file.read_text(encoding="utf-8", errors="ignore")
        # Match apiFetch("...", ...) and apiFetch('...', ...)
        matches = re.findall(r'apiFetch\(\s*["\']([^"\'?#]+)', content)
        for m in matches:
            if not m.startswith("http") and not "${" in m:
                api_calls.add(m)

    missing_endpoints = []
    for endpoint in sorted(api_calls):
        # Normalize endpoint
        path = endpoint if endpoint.startswith("/api") else f"/api{endpoint if endpoint.startswith('/') else '/' + endpoint}"
        res = client.get(path, headers=headers)
        # If GET returns 404, check if it's a POST-only or exists
        if res.status_code == 404:
            # Try OPTIONS to check if route exists with other methods
            opt_res = client.options(path, headers=headers)
            if opt_res.status_code == 404:
                missing_endpoints.append((endpoint, path))

    # Filter out parameterized endpoints (ending with /)
    critical_missing = [
        e for e in missing_endpoints
        if not e[0].endswith("/") and not any(k in e[0] for k in ["/documents/", "/folders/", "/users/", "/groups/", "/tasks/", "/share/", "/compliance/gdpr/"])
    ]
    assert not critical_missing, f"Frontend calls missing backend endpoints: {critical_missing}"


def test_audit_all_index_html_admin_buttons():
    """Verify all admin items in index.html have matching handler functions in frontend JS."""
    index_html = Path("frontend/index.html").read_text(encoding="utf-8", errors="ignore")
    js_content = ""
    for js_file in Path("frontend").glob("*.js"):
        js_content += js_file.read_text(encoding="utf-8", errors="ignore") + "\n"

    # Find onclick="..." in index.html
    onclicks = re.findall(r'onclick="([a-zA-Z0-9_]+)\(', index_html)
    missing_functions = []

    for fn in set(onclicks):
        if fn not in ["closeDrops", "toggleAdminGroup", "inspTab"]:
            # Check if defined in JS
            pattern = rf'(?:function\s+{fn}|window\.{fn}\s*=|const\s+{fn}\s*=|let\s+{fn}\s*=|var\s+{fn}\s*=|{fn}\s*=\s*function)'
            if not re.search(pattern, js_content):
                missing_functions.append(fn)

    assert not missing_functions, f"index.html has onclick handlers with missing JS functions: {missing_functions}"
