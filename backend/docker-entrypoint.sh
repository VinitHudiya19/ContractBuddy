#!/usr/bin/env bash
# Runs DB migrations before starting the app. Idempotent: safe on every boot.
set -e

echo "[entrypoint] waiting for Postgres to accept connections..."
python - <<'PY'
import os, time, asyncio, asyncpg, urllib.parse as up

url = os.environ["DATABASE_URL"].replace("+asyncpg", "")
parsed = up.urlparse(url)

async def wait():
    for attempt in range(30):
        try:
            conn = await asyncpg.connect(
                user=parsed.username, password=parsed.password,
                database=parsed.path.lstrip("/"),
                host=parsed.hostname, port=parsed.port or 5432,
            )
            await conn.close()
            print("[entrypoint] Postgres is ready.")
            return
        except Exception as e:  # noqa: BLE001
            print(f"[entrypoint] Postgres not ready ({attempt+1}/30): {e}")
            time.sleep(2)
    raise SystemExit("[entrypoint] Postgres never became ready.")

asyncio.run(wait())
PY

echo "[entrypoint] running Alembic migrations..."
alembic upgrade head

echo "[entrypoint] seeding bootstrap admin (idempotent)..."
python -m scripts.seed || echo "[entrypoint] seed skipped/failed (non-fatal)."

echo "[entrypoint] launching: $*"
exec "$@"
