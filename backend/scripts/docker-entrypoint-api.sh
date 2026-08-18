#!/bin/bash
# Production entrypoint for the FastAPI web process.
# Waits for Postgres, bootstraps schema, then hands off to uvicorn/gunicorn via exec
# so SIGTERM/SIGINT reach the Python process (clean container stop).
set -euo pipefail

# `python scripts/foo.py` puts scripts/ on sys.path, not /app — force the package root.
export PYTHONPATH="/app${PYTHONPATH:+:$PYTHONPATH}"
cd /app

HOST="${HOST:-0.0.0.0}"
PORT="${PORT:-8000}"
WORKERS="${GUNICORN_WORKERS:-4}"
TIMEOUT="${GUNICORN_TIMEOUT:-120}"
# Keep LOG_LEVEL intact for Python/Loguru (expects INFO). Gunicorn wants lowercase.
GUNICORN_LOG_LEVEL="$(echo "${LOG_LEVEL:-info}" | tr '[:upper:]' '[:lower:]')"
APP_MODULE="${APP_MODULE:-main:app}"
MAX_DB_ATTEMPTS="${MAX_DB_ATTEMPTS:-60}"
# Gunicorn 26 control socket defaults to $HOME/.gunicorn which is not writable
# for the non-root appuser (HOME=/app).
export XDG_RUNTIME_DIR="${XDG_RUNTIME_DIR:-/tmp}"

log() {
  printf '[entrypoint-api] %s\n' "$*"
}

wait_for_postgres() {
  log "Waiting for PostgreSQL (${MAX_DB_ATTEMPTS} attempts)..."
  python - <<'PY'
import os
import sys
import time
from urllib.parse import urlparse, unquote

database_url = os.environ.get("DATABASE_URL", "")
if not database_url:
    print("[entrypoint-api] DATABASE_URL is not set", file=sys.stderr)
    sys.exit(1)

parsed = urlparse(database_url.replace("postgresql+asyncpg://", "postgresql://", 1))
host = parsed.hostname or "postgres"
port = parsed.port or 5432
user = unquote(parsed.username or "postgres")
password = unquote(parsed.password or "")
dbname = (parsed.path or "/postgres").lstrip("/") or "postgres"
attempts = int(os.environ.get("MAX_DB_ATTEMPTS", "60"))

# Prefer pg_isready when the client tools are present.
import shutil
import subprocess

if shutil.which("pg_isready"):
    env = os.environ.copy()
    if password:
        env["PGPASSWORD"] = password
    for attempt in range(1, attempts + 1):
        result = subprocess.run(
            ["pg_isready", "-h", host, "-p", str(port), "-U", user, "-d", dbname],
            env=env,
            capture_output=True,
            text=True,
        )
        if result.returncode == 0:
            print(f"[entrypoint-api] PostgreSQL ready via pg_isready (attempt {attempt})")
            sys.exit(0)
        print(f"[entrypoint-api] pg_isready not ready ({attempt}/{attempts})")
        time.sleep(2)
    print("[entrypoint-api] Timed out waiting for PostgreSQL (pg_isready)", file=sys.stderr)
    sys.exit(1)

# Fallback: TCP + optional asyncpg auth probe.
import socket

for attempt in range(1, attempts + 1):
    try:
        with socket.create_connection((host, port), timeout=3):
            pass
        try:
            import asyncpg
            import asyncio

            async def _ping() -> None:
                conn = await asyncpg.connect(
                    host=host,
                    port=port,
                    user=user,
                    password=password or None,
                    database=dbname,
                    timeout=5,
                )
                await conn.close()

            asyncio.run(_ping())
        except ImportError:
            pass
        print(f"[entrypoint-api] PostgreSQL reachable (attempt {attempt})")
        sys.exit(0)
    except Exception as exc:
        print(f"[entrypoint-api] DB wait {attempt}/{attempts}: {exc}")
        time.sleep(2)

print("[entrypoint-api] Timed out waiting for PostgreSQL", file=sys.stderr)
sys.exit(1)
PY
}

run_bootstrap() {
  if [[ "${SKIP_BOOTSTRAP:-false}" == "true" ]]; then
    log "SKIP_BOOTSTRAP=true — skipping schema bootstrap."
    return 0
  fi

  local bootstrap_script="scripts/bootstrap_database.py"
  if [[ ! -f "${bootstrap_script}" ]]; then
    log "Bootstrap script not found at ${bootstrap_script} — skipping."
    return 0
  fi

  log "Running: python ${bootstrap_script}..."
  python "${bootstrap_script}"
  log "Schema bootstrap complete."
}

run_migrations() {
  if [[ "${SKIP_MIGRATIONS:-false}" == "true" ]]; then
    log "SKIP_MIGRATIONS=true — skipping alembic upgrade head."
    return 0
  fi

  # create_all already materializes the current ORM schema. If Alembic has
  # never been stamped, upgrade would re-run additive migrations and fail
  # on duplicate columns/tables. Stamp head first, then upgrade (no-op or
  # applies any revision newer than the models).
  set +e
  python - <<'PY'
import asyncio
import os
import sys

from sqlalchemy import text
from sqlalchemy.ext.asyncio import create_async_engine

async def main() -> int:
    engine = create_async_engine(os.environ["DATABASE_URL"])
    try:
        async with engine.connect() as conn:
            users = await conn.scalar(
                text(
                    "SELECT EXISTS (SELECT 1 FROM information_schema.tables "
                    "WHERE table_schema = 'public' AND table_name = 'users')"
                )
            )
            has_version_table = await conn.scalar(
                text(
                    "SELECT EXISTS (SELECT 1 FROM information_schema.tables "
                    "WHERE table_schema = 'public' AND table_name = 'alembic_version')"
                )
            )
            version = None
            if has_version_table:
                version = await conn.scalar(
                    text("SELECT version_num FROM alembic_version LIMIT 1")
                )
    finally:
        await engine.dispose()
    if users and not version:
        return 2
    return 0

raise SystemExit(asyncio.run(main()))
PY
  local py_rc=$?
  set -e

  if [[ "${py_rc}" -eq 2 ]]; then
    log "ORM schema present without Alembic stamp — running: alembic stamp head"
    if ! alembic stamp head; then
      log "ERROR: alembic stamp head failed." >&2
      exit 1
    fi
  elif [[ "${py_rc}" -ne 0 ]]; then
    log "WARN: could not inspect alembic_version (exit ${py_rc}); continuing with upgrade."
  fi

  log "Running: alembic upgrade head..."
  if ! alembic upgrade head; then
    log "ERROR: alembic upgrade head failed." >&2
    exit 1
  fi
  log "Migrations applied."
}

run_seed() {
  if [[ "${SKIP_SEED:-false}" == "true" ]]; then
    log "SKIP_SEED=true — skipping seed_initial_data."
    return 0
  fi

  local seed_script="scripts/seed_initial_data.py"
  if [[ ! -f "${seed_script}" ]]; then
    log "Seed script not found at ${seed_script} — skipping."
    return 0
  fi

  log "Running: python ${seed_script}..."
  python "${seed_script}" || log "WARN: seed_initial_data.py reported an error; platform will start anyway."
}

start_api() {
  # Allow compose/CMD overrides: remaining args replace the default server command.
  if [[ "$#" -gt 0 ]]; then
    log "Executing override command: $*"
    exec "$@"
  fi

  if [[ "${UVICORN_ONLY:-false}" == "true" ]]; then
    log "Starting uvicorn (${APP_MODULE}) workers=${WORKERS} on ${HOST}:${PORT}"
    exec uvicorn "${APP_MODULE}" \
      --host "${HOST}" \
      --port "${PORT}" \
      --workers "${WORKERS}" \
      --proxy-headers \
      --forwarded-allow-ips='*' \
      --log-level "${GUNICORN_LOG_LEVEL}"
  fi

  if command -v gunicorn >/dev/null 2>&1; then
    log "Starting gunicorn+uvicorn (${APP_MODULE}) workers=${WORKERS} on ${HOST}:${PORT}"
    exec gunicorn "${APP_MODULE}" \
      -k uvicorn.workers.UvicornWorker \
      -w "${WORKERS}" \
      --bind "${HOST}:${PORT}" \
      --timeout "${TIMEOUT}" \
      --graceful-timeout 30 \
      --keep-alive 5 \
      --access-logfile - \
      --error-logfile - \
      --control-socket /tmp/gunicorn.ctl \
      --log-level "${GUNICORN_LOG_LEVEL}"
  fi

  log "gunicorn not found — falling back to uvicorn workers=${WORKERS}"
  exec uvicorn "${APP_MODULE}" \
    --host "${HOST}" \
    --port "${PORT}" \
    --workers "${WORKERS}" \
    --proxy-headers \
    --forwarded-allow-ips='*' \
    --log-level "${LOG_LEVEL}"
}

wait_for_postgres
run_bootstrap
run_migrations
run_seed
start_api "$@"
