#!/usr/bin/env bash
# Container entrypoint: wait for the database, apply migrations, then serve.
set -e

echo "[entrypoint] Applying database migrations (alembic upgrade head)..."
for attempt in $(seq 1 15); do
    if alembic upgrade head; then
        echo "[entrypoint] Migrations applied."
        break
    fi
    echo "[entrypoint] Database not ready yet (attempt ${attempt}/15), retrying in 2s..."
    sleep 2
done

echo "[entrypoint] Starting Uvicorn..."
exec uvicorn app.main:app --host 0.0.0.0 --port 8000
