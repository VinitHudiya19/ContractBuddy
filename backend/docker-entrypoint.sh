#!/usr/bin/env bash
# Prepares the database, then hands off to the CMD.
# Idempotent: safe to run on every container start.
set -e

DB_URL="${DATABASE_URL:-}"

# Only Postgres gets the wait + migrations. The first migration creates a GIN
# index, which is Postgres-only, so on SQLite we let the app create its own
# tables instead. That way the same image runs with or without a database
# server attached.
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
    echo "[entrypoint] applying migrations..."
    alembic upgrade head
    ;;
  *)
    echo "[entrypoint] no Postgres configured — the app will create its own schema."
    ;;
esac

echo "[entrypoint] starting: $*"
exec "$@"
