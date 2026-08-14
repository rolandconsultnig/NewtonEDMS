"""Entry point: run the NewEDMS API with uvicorn.

The application lives in the ``app`` package; this module simply boots it.
``app.main:app`` is the ASGI app reference (e.g. for ``uvicorn app.main:app``).
"""
from __future__ import annotations

import uvicorn

from app.config import settings

if __name__ == "__main__":
    uvicorn.run(
        "app.main:app",
        host=settings.server_host,
        port=settings.server_port,
        reload=False,
    )
