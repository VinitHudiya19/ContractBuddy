#!/usr/bin/env bash
# Applies migrations and seeds the admin account, then hands off to the CMD.
# Idempotent: safe to run on every container start.
set -e

DB_URL="${DATABASE_URL:-}"

# Only Postgres needs a readiness wait. With SQLite (the default) the database
# is a local file, so the app can run as a single container with no services
# attached — which is what makes `docker run` alone a valid deployment.
case "$DB_URL" in
  *postgres*)
    echo "[entrypoint] waiting for Postgres..."
    python - <<'PY'
import os, time, asyncio, asyncpg, urllib.parse as up

parsed = up.urlparse(os.environ["DATABASE_URL"].replace("+asyncpg", ""))

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
            print(f"[entrypoint] Postgres not ready ({attempt + 1}/30): {e}")
            time.sleep(2)
    raise SystemExit("[entrypoint] Postgres never became ready.")

asyncio.run(wait())
PY
    ;;
  *)
    echo "[entrypoint] no Postgres configured — using the local database."
    ;;
esac

echo "[entrypoint] applying migrations..."
alembic upgrade head

echo "[entrypoint] seeding bootstrap admin (idempotent)..."
python -m scripts.seed || echo "[entrypoint] seed skipped (non-fatal)."

echo "[entrypoint] starting: $*"
exec "$@"
