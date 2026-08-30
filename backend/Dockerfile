# Contract Buddy backend image.
#
# The image is large (~2 GB) because sentence-transformers needs CPU torch.
# Model weights download on first run into /app/.cache, kept as a volume in
# compose so it only happens once.
#
# Build from the repo root, not from backend/:
#     docker build -f backend/Dockerfile -t contractbuddy .
FROM python:3.12-slim

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1 \
    HF_HOME=/app/.cache/huggingface

# torch needs libgomp1 at runtime. build-essential is for any package
# without a prebuilt wheel.
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

# Run as a non-root user. Cache and uploads sit under /app so this user
# can write to them.
RUN useradd -m appuser \
    && mkdir -p /app/storage /app/.cache \
    && chown -R appuser:appuser /app
USER appuser

EXPOSE 8000

# Entrypoint sets up the database, then runs the command below.
ENTRYPOINT ["docker-entrypoint.sh"]
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
