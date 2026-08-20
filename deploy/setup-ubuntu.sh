#!/usr/bin/env bash
# NewtonEDMS production installer for Ubuntu (native, no Docker).
#
# Run ON the Linux server, as root, from the repository root:
#   sudo bash deploy/setup-ubuntu.sh [server_name_for_nginx]
#
# What it does (idempotent — safe to re-run to deploy new code):
#   1. system user + directories (/opt/newedms, /var/lib/newedms, /etc/newedms)
#   2. rsync application code to /opt/newedms
#   3. python3.12 virtualenv + pinned requirements.lock
#   4. environment file /etc/newedms/newedms.env (secret generated once, kept on re-runs)
#   5. systemd service (migrations on boot, auto-restart, sandboxed)
#   6. nginx reverse proxy site (skipped when nginx is not installed)
#   7. health check against 127.0.0.1:8000
#
# Default first-boot admin credentials: admin / admin123
# Override BEFORE first run with:  EDMS_SEED_ADMIN_PASSWORD='...' sudo -E bash deploy/setup-ubuntu.sh
set -euo pipefail

APP_USER=newedms
APP_DIR=/opt/newedms
DATA_DIR=/var/lib/newedms
ENV_DIR=/etc/newedms
ENV_FILE=$ENV_DIR/newedms.env
SERVICE_NAME=newedms
NGINX_SERVER_NAME="${1:-_}"   # "_" = respond to any host; pass edms.example.com otherwise
SEED_PW="${EDMS_SEED_ADMIN_PASSWORD:-admin123}"

if [ "$(id -u)" -ne 0 ]; then
  echo "ERROR: run as root (sudo bash deploy/setup-ubuntu.sh)" >&2
  exit 1
fi
REPO_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$REPO_DIR"
echo "==> Installing NewtonEDMS from $REPO_DIR"

# ---- Python ----------------------------------------------------------------
PY=python3.12
if ! command -v $PY >/dev/null 2>&1; then
  if command -v python3 >/dev/null 2>&1 && python3 -c 'import sys; sys.exit(0 if sys.version_info >= (3,12) else 1)'; then
    PY=python3
  else
    echo "ERROR: Python 3.12+ required. On Ubuntu <= 24.04:" >&2
    echo "  sudo add-apt-repository ppa:deadsnakes/ppa && sudo apt-get update && sudo apt-get install -y python3.12 python3.12-venv" >&2
    exit 1
  fi
fi
command -v rsync >/dev/null 2>&1 || apt-get update -qq && apt-get install -y -qq rsync >/dev/null

# ---- User + directories ------------------------------------------------------
if ! id "$APP_USER" >/dev/null 2>&1; then
  useradd --system --home "$APP_DIR" --shell /usr/sbin/nologin "$APP_USER"
fi
mkdir -p "$APP_DIR" "$DATA_DIR/storage" "$ENV_DIR"
chown -R "$APP_USER:$APP_USER" "$DATA_DIR"

# ---- Application code --------------------------------------------------------
rsync -a --delete \
  --exclude .git --exclude .github --exclude .vscode \
  --exclude venv --exclude .venv --exclude node_modules \
  --exclude community-master --exclude docspell-master \
  --exclude 'community-master.zip' --exclude 'docspell-master.zip' \
  --exclude storage --exclude 'edms.db*' --exclude .env \
  --exclude tests --exclude __pycache__ \
  "$REPO_DIR"/ "$APP_DIR"/
chown -R "$APP_USER:$APP_USER" "$APP_DIR"

# ---- Virtualenv + pinned dependencies ---------------------------------------
if [ ! -x "$APP_DIR/venv/bin/pip" ]; then
  $PY -m venv "$APP_DIR/venv"
fi
"$APP_DIR/venv/bin/pip" install --quiet --upgrade -r "$APP_DIR/requirements.lock"
chown -R "$APP_USER:$APP_USER" "$APP_DIR/venv"

# ---- Environment file (created once; secret survives re-deploys) ------------
if [ ! -f "$ENV_FILE" ]; then
  SECRET=$(openssl rand -hex 32 2>/dev/null || $PY -c "import secrets; print(secrets.token_hex(32))")
  cat > "$ENV_FILE" <<EOF
EDMS_SECRET_KEY=$SECRET
EDMS_STORAGE_DIR=$DATA_DIR/storage
EDMS_DATABASE_URL=sqlite:///$DATA_DIR/edms.db
EDMS_SEED_ADMIN_PASSWORD=$SEED_PW
EOF
  chown "$APP_USER:$APP_USER" "$ENV_FILE"
  chmod 600 "$ENV_FILE"
  echo "==> Created $ENV_FILE (admin password: as configured; change it after first login)"
else
  echo "==> Keeping existing $ENV_FILE"
fi

# ---- systemd -----------------------------------------------------------------
cp deploy/newedms.service /etc/systemd/system/
systemctl daemon-reload
systemctl enable "$SERVICE_NAME" >/dev/null
systemctl restart "$SERVICE_NAME"

# ---- Health check --------------------------------------------------------------
echo "==> Waiting for application..."
ok=""
for i in $(seq 1 30); do
  if curl -fsS http://127.0.0.1:8000/api/system/health >/dev/null 2>&1; then ok=1; break; fi
  sleep 2
done
if [ -z "$ok" ]; then
  echo "ERROR: service did not become healthy. Inspect with: journalctl -u $SERVICE_NAME -n 50" >&2
  exit 1
fi
echo "==> Healthy: $(curl -fsS http://127.0.0.1:8000/api/system/health)"

# ---- nginx (optional) ----------------------------------------------------------
if command -v nginx >/dev/null 2>&1; then
  sed "s/server_name edms.example.com;/server_name $NGINX_SERVER_NAME;/" \
    deploy/nginx-newedms.conf > /etc/nginx/sites-available/newedms
  ln -sf /etc/nginx/sites-available/newedms /etc/nginx/sites-enabled/newedms
  nginx -t
  systemctl reload nginx
  echo "==> nginx site installed (server_name: $NGINX_SERVER_NAME)"
else
  echo "==> nginx not installed — skipped (app answers on 127.0.0.1:8000)"
fi

echo
echo "Deployment complete."
echo "  Local probe : curl http://127.0.0.1:8000/api/system/health"
echo "  Logs        : journalctl -u $SERVICE_NAME -f"
echo "  Login       : admin / (EDMS_SEED_ADMIN_PASSWORD from $ENV_FILE; default admin123)"
echo "Next steps:"
echo "  1. Change the admin password in the UI immediately."
echo "  2. Put TLS in front (certbot --nginx -d your.domain), then set"
echo "     EDMS_COOKIE_SECURE=true in $ENV_FILE and: systemctl restart $SERVICE_NAME"
echo "  3. Re-run this script any time to deploy updated code (data is preserved)."
