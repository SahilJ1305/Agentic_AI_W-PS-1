# Cadence API + Telegram bot + scheduler (one process; see README, "Deploy").
FROM python:3.12-slim

WORKDIR /srv
ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    APP_HOST=0.0.0.0 \
    APP_PORT=8000 \
    DATABASE_PATH=/srv/data/cadence.db

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Secrets are never baked into the image: .env is excluded by .dockerignore and
# supplied at run time (env_file / platform settings).
COPY app ./app
COPY docs ./docs
COPY scripts ./scripts
RUN mkdir -p /srv/data

EXPOSE 8000
HEALTHCHECK --interval=30s --timeout=6s --start-period=20s \
  CMD python -c "import httpx; httpx.get('http://127.0.0.1:8000/api/health', timeout=5).raise_for_status()"

# Exactly ONE copy of this container may run per Telegram bot token.
CMD ["python", "-m", "app.main"]
