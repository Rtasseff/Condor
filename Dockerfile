# Condor Funds v2 — single-container deploy (docs/DEPLOY.md).
# NOTE: authored 2026-08-23, not yet built in CI — the first deploy
# validates it. Python 3.11 to match the development venv.
FROM python:3.11-slim

ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1
WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY condor/ condor/
COPY web/ web/

# static files are baked into the image (whitenoise serves them);
# dev-default settings are fine at build time
RUN python web/manage.py collectstatic --noinput

# Runtime expectations (set by the platform / fly.toml / compose):
#   CONDOR_SECRET_KEY   long random string
#   CONDOR_DEBUG=0
#   CONDOR_ALLOWED_HOSTS=condor.example.com
#   CONDOR_CSRF_ORIGINS=https://condor.example.com
#   CONDOR_DB_PATH=/data/db.sqlite3        (persistent volume)
#   CONDOR_DATA_DIR=/data/condor           (price store on the volume)
#   TIINGO_API_KEY=...                     (yfinance failover — get one)
EXPOSE 8000
CMD ["sh", "-c", "python web/manage.py migrate --noinput && \
     exec gunicorn config.wsgi:application --chdir web \
     --bind 0.0.0.0:8000 --workers 2 --timeout 120"]
