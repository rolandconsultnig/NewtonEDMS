module.exports = {
  apps: [
    {
      name: "newton-edms",
      cwd: "/var/www/newton",
      script: "/var/www/newton/venv/bin/uvicorn",
      args: "app.main:app --host 127.0.0.1 --port 8000 --workers 4 --proxy-headers --forwarded-allow-ips='*'",
      interpreter: "none",
      env: {
        PYTHONUNBUFFERED: "1",
        EDMS_ENV: "production"
      },
      autorestart: true,
      max_memory_restart: "1G",
      log_date_format: "YYYY-MM-DD HH:mm:ss Z",
      error_file: "/var/log/newton/error.log",
      out_file: "/var/log/newton/out.log",
      merge_logs: true
    }
  ]
};
