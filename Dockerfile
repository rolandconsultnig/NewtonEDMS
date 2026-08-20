# NewtonEDMS production image.
#
# SQLite + local storage means this is a single-node deployment: keep workers=1
# and mount a volume at /data (database + uploaded files). For multi-worker or
# HA setups point EDMS_DATABASE_URL at Postgres and storage at shared/object
# storage first.
FROM python:3.12-slim

ENV PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    EDMS_STORAGE_DIR=/data/storage \
    EDMS_DATABASE_URL=sqlite:////data/edms.db

WORKDIR /srv/newtonedms

# Install pinned runtime dependencies first for better layer caching.
COPY requirements.txt requirements.lock ./
RUN pip install --no-cache-dir -r requirements.lock

# Application code (frontend/tailwind.css + vendored fonts are committed, so no
# node build is needed here).
COPY app ./app
COPY frontend ./frontend
COPY alembic ./alembic
COPY alembic.ini main.py ./

RUN mkdir -p /data/storage
VOLUME ["/data"]
EXPOSE 8000

# Run migrations on boot, then serve.
CMD ["sh", "-c", "alembic upgrade head && uvicorn app.main:app --host 0.0.0.0 --port 8000 --workers 1"]
