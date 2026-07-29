# Root Dockerfile — for platforms that auto-detect a Dockerfile at the repo root
# and build with the repo root as context (Koyeb, Zeabur, Railway, Render, etc.).
#
# Builds the slim backend (no torch) so it fits free/small instances. The DB is
# external (Neon) — set DATABASE_URL in the platform's env vars. Listens on $PORT.
FROM python:3.12-slim

ENV PYTHONUNBUFFERED=1 PYTHONDONTWRITEBYTECODE=1 PIP_NO_CACHE_DIR=1
WORKDIR /app

RUN apt-get update && apt-get install -y --no-install-recommends \
        build-essential curl libgomp1 && rm -rf /var/lib/apt/lists/*

COPY backend/requirements-serve.txt .
RUN pip install --no-cache-dir -r requirements-serve.txt

COPY backend/services ./services
COPY backend/scripts ./scripts
COPY backend/db ./db

RUN useradd --create-home --shell /bin/false cerebro && chown -R cerebro:cerebro /app
USER cerebro

EXPOSE 8000
CMD ["sh", "-c", "uvicorn services.api.main:app --host 0.0.0.0 --port ${PORT:-8000}"]
