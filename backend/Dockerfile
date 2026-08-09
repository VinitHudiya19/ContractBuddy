# =============================================================================
#  Backend image — FastAPI + async RAG pipeline
#  Multi-stage kept simple; sentence-transformers pulls torch, so the image is
#  intentionally sizeable. Model weights download on first run into /root/.cache
#  (mounted as a named volume so they persist across restarts).
# =============================================================================
FROM python:3.12-slim AS base

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1 \
    HF_HOME=/root/.cache/huggingface

# System deps: build tools for a few wheels; libgomp for torch/sentence-transformers.
RUN apt-get update && apt-get install -y --no-install-recommends \
        build-essential \
        libgomp1 \
        curl \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

# Install Python deps first for better layer caching.
COPY backend/requirements.txt .
RUN pip install --upgrade pip && pip install --no-cache-dir -r requirements.txt

# Backend code, then the static UI that main.py mounts at "/".
COPY backend/ .
COPY frontend/ ./frontend/

# Non-root user.
RUN useradd -m appuser && mkdir -p /app/storage && chown -R appuser:appuser /app
# Note: model cache volume is owned by root; keep default user for cache writes
# in compose (root) — acceptable for a local/portfolio deployment.

EXPOSE 8000

# The entrypoint runs migrations then launches uvicorn.
COPY backend/docker-entrypoint.sh /usr/local/bin/docker-entrypoint.sh
RUN chmod +x /usr/local/bin/docker-entrypoint.sh

ENTRYPOINT ["docker-entrypoint.sh"]
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
