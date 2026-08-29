# =============================================================================
#  Contract Buddy — backend image (FastAPI + local embeddings + RAG pipeline)
#
#  sentence-transformers pulls CPU torch, so the image is large (~2 GB) by
#  nature. Model weights are downloaded on first run into /app/.cache, which is
#  a volume in compose so the download happens once.
#
#  Build from the repo root, not backend/:
#      docker build -f backend/Dockerfile -t contractbuddy .
# =============================================================================
FROM python:3.12-slim

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1 \
    HF_HOME=/app/.cache/huggingface

# libgomp1 is required by torch at runtime; build-essential covers any package
# that has no prebuilt wheel for this platform.
RUN apt-get update && apt-get install -y --no-install-recommends \
        build-essential \
        libgomp1 \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

# Dependencies first so code edits do not invalidate the (slow) install layer.
COPY backend/requirements.txt .
RUN pip install --upgrade pip && pip install --no-cache-dir -r requirements.txt

# Backend code, then the static UI that main.py mounts at "/".
COPY backend/ .
COPY frontend/ ./frontend/

COPY backend/docker-entrypoint.sh /usr/local/bin/docker-entrypoint.sh
RUN chmod +x /usr/local/bin/docker-entrypoint.sh

# Run as a non-root user. The model cache and upload dir live under /app so the
# same user that runs the app can write to them without a root-owned volume.
RUN useradd -m appuser \
    && mkdir -p /app/storage /app/.cache \
    && chown -R appuser:appuser /app
USER appuser

EXPOSE 8000

# Entrypoint applies migrations and seeds the admin, then execs the command.
ENTRYPOINT ["docker-entrypoint.sh"]
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
