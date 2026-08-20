# NewtonEDMS Production Deployment Guide

Target: Ubuntu 22.04/24.04, `/var/www/newton`, PostgreSQL, PM2, nginx.

## 1. Server layout

```text
/var/www/newton          # application code (this repo)
/var/www/newton/venv     # Python virtualenv
/var/log/newton          # PM2/out/error logs
```

## 2. PostgreSQL

Create the database and a dedicated user:

```bash
sudo -u postgres psql -c "CREATE USER newton WITH PASSWORD 'YOUR_STRONG_PASSWORD';"
sudo -u postgres psql -c "CREATE DATABASE newton OWNER newton;"
sudo -u postgres psql -c "GRANT ALL PRIVILEGES ON DATABASE newton TO newton;"
```

## 3. Environment file

Create the production env file. `app.config` reads from `EDMS_*` variables or `.env` in the repo root.

```bash
sudo mkdir -p /etc/newedms
sudo nano /etc/newedms/newedms.env
```

Example:

```ini
EDMS_SECRET_KEY=change-me-to-a-64-char-random-string
EDMS_ALGORITHM=HS256
EDMS_ACCESS_TOKEN_EXPIRE_MINUTES=240
EDMS_DATABASE_URL=postgresql+psycopg2://newton:YOUR_STRONG_PASSWORD@127.0.0.1:5432/newton
EDMS_CORS_ORIGINS=https://edms.example.com,https://www.edms.example.com
EDMS_STORAGE_DIR=/var/www/newton/storage
EDMS_MAX_UPLOAD_BYTES=52428800
EDMS_SERVER_HOST=127.0.0.1
EDMS_SERVER_PORT=8000
EDMS_LOG_LEVEL=INFO
EDMS_COOKIE_NAME=newton_token
EDMS_COOKIE_SECURE=true
EDMS_COOKIE_SAMESITE=lax
EDMS_SEED_ADMIN_USERNAME=admin
EDMS_SEED_ADMIN_PASSWORD=admin123
EDMS_SMTP_FROM=noreply@edms.example.com
EDMS_FTS_BACKEND=postgres
EDMS_SOLR_URL=
EDMS_ONLYOFFICE_URL=
EDMS_OFFICE_ONLINE_URL=
EDMS_WOPI_CLIENT_URL=
```

Link it to the app root so it is picked up automatically:

```bash
ln -sf /etc/newedms/newedms.env /var/www/newton/.env
```

## 4. Virtualenv and dependencies

```bash
cd /var/www/newton
python3 -m venv venv
venv/bin/pip install --upgrade pip
venv/bin/pip install -r requirements.txt
```

The production database driver is usually installed separately:

```bash
venv/bin/pip install psycopg2-binary
```

## 5. Static / log directories

```bash
sudo mkdir -p /var/log/newton
sudo chown -R www-data:www-data /var/log/newton
sudo mkdir -p /var/www/newton/storage
sudo chown -R www-data:www-data /var/www/newton/storage
```

## 6. PM2

The repo already ships `ecosystem.config.js`.

```bash
cd /var/www/newton
pm2 start ecosystem.config.js
pm2 save
pm2 startup systemd
```

Useful commands:

```bash
pm2 restart newton-edms
pm2 logs newton-edms --lines 50
pm2 reload newton-edms
```

## 7. Nginx

```bash
sudo cp /var/www/newton/deploy/nginx-newedms.conf /etc/nginx/sites-available/newedms
sudo ln -sf /etc/nginx/sites-available/newedms /etc/nginx/sites-enabled/newedms
sudo nginx -t
sudo systemctl reload nginx
```

The supplied config listens on `2080`. For TLS run:

```bash
sudo apt install certbot python3-certbot-nginx
sudo certbot --nginx -d edms.example.com
```

Then set `EDMS_COOKIE_SECURE=true` and restart PM2.

## 8. Deploy / update flow

```bash
cd /var/www/newton
git fetch origin
git reset --hard origin/main
git pull
venv/bin/pip install -r requirements.txt
pm2 restart newton-edms
pm2 logs newton-edms --lines 20
```

## 9. Troubleshooting

### 9.1 Duplicate admin on startup

If you see:

```text
psycopg2.errors.UniqueViolation: duplicate key value violates unique constraint "ix_users_username"
DETAIL:  Key (username)=(admin) already exists.
```

This is a multi-worker startup race. The fix is in `app/seeding.py`:

- Replace `from app.security import pwd_context` with `from app.security import get_password_hash`.
- Query for the existing `admin` user before inserting.
- Wrap the `db.commit()` calls in a `try/except IntegrityError` block and call `db.rollback()` on conflict.

After patching, restart:

```bash
pm2 restart newton-edms
```

### 9.2 `passlib` bcrypt error

If you see passlib `ValueError: password cannot be longer than 72 bytes`, ensure `app/security.py` uses direct `bcrypt` and that `app/seeding.py` no longer imports or uses `pwd_context`.

`app/security.py` should be roughly:

```python
import bcrypt

def verify_password(plain: str, hashed: str) -> bool:
    if not plain or not hashed:
        return False
    try:
        return bcrypt.checkpw(plain.encode("utf-8")[:72], hashed.encode("utf-8"))
    except Exception:
        return False

def get_password_hash(password: str) -> str:
    pwd_bytes = password.encode("utf-8")[:72]
    salt = bcrypt.gensalt()
    return bcrypt.hashpw(pwd_bytes, salt).decode("utf-8")
```

### 9.3 Admin password not working

Reset it directly in PostgreSQL:

```bash
cd /var/www/newton
venv/bin/python - <<'PY'
import bcrypt, os, sys
os.environ.setdefault('EDMS_DATABASE_URL','postgresql+psycopg2://newton:YOUR_STRONG_PASSWORD@127.0.0.1:5432/newton')
sys.path.insert(0,'/var/www/newton')
from app.database import SessionLocal
from app.models import User
hpw = bcrypt.hashpw('admin123'.encode(), bcrypt.gensalt()).decode()
db = SessionLocal()
u = db.query(User).filter(User.username == 'admin').first()
if u:
    u.hashed_password = hpw
    u.is_active = True
    db.commit()
    print('admin password reset')
else:
    print('admin not found')
PY
```

Then:

```bash
pm2 restart newton-edms
```
