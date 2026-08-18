#!/usr/bin/env bash
# =============================================================================
# MP.AI backend — unified dev entrypoint
#
# Lifecycle:
#   1. Wait for PostgreSQL to accept connections
#   2. Wait for Redis to respond to PING
#   3. Apply database migrations:  alembic upgrade head
#   4. Seed initial system data:   python scripts/seed_initial_data.py
#   5. exec → hand off to CMD (uvicorn / celery / shell override)
#
# Usage in Dockerfile:
#   ENTRYPOINT ["/app/entrypoint.sh"]
#   CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000", "--reload"]
#
# Usage in docker-compose (override CMD):
#   command: ["celery", "-A", "app.core.celery_app", "worker", "--loglevel=info"]
# =============================================================================
set -euo pipefail

# ── Logging ──────────────────────────────────────────────────────────────────
log()  { printf '\033[36m[entrypoint]\033[0m %s\n' "$*"; }
ok()   { printf '\033[32m[entrypoint][OK]\033[0m %s\n' "$*"; }
warn() { printf '\033[33m[entrypoint][WARN]\033[0m %s\n' "$*"; }
fail() { printf '\033[31m[entrypoint][FAIL]\033[0m %s\n' "$*" >&2; exit 1; }

# ── Configuration ─────────────────────────────────────────────────────────────
MAX_DB_ATTEMPTS="${MAX_DB_ATTEMPTS:-60}"
MAX_REDIS_ATTEMPTS="${MAX_REDIS_ATTEMPTS:-30}"
WAIT_INTERVAL="${WAIT_INTERVAL:-2}"

SKIP_MIGRATIONS="${SKIP_MIGRATIONS:-false}"
SKIP_SEED="${SKIP_SEED:-false}"

# ── 1. Wait for PostgreSQL ────────────────────────────────────────────────────
wait_for_postgres() {
  log "Waiting for PostgreSQL (up to $((MAX_DB_ATTEMPTS * WAIT_INTERVAL))s)…"
  python - <<'PY'
import os, sys, time, socket
from urllib.parse import urlparse, unquote
import shutil, subprocess

url = os.environ.get("DATABASE_URL", "")
if not url:
    print("[entrypoint] DATABASE_URL is not set", file=sys.stderr)
    sys.exit(1)

parsed  = urlparse(url.replace("postgresql+asyncpg://", "postgresql://", 1))
host    = parsed.hostname or "postgres"
port    = parsed.port or 5432
user    = unquote(parsed.username or "postgres")
password = unquote(parsed.password or "")
dbname  = (parsed.path or "/postgres").lstrip("/") or "postgres"
attempts = int(os.environ.get("MAX_DB_ATTEMPTS", "60"))
interval = int(os.environ.get("WAIT_INTERVAL", "2"))

# Prefer pg_isready (available in postgres-client packages).
if shutil.which("pg_isready"):
    env = os.environ.copy()
    if password:
        env["PGPASSWORD"] = password
    for i in range(1, attempts + 1):
        r = subprocess.run(
            ["pg_isready", "-h", host, "-p", str(port), "-U", user, "-d", dbname],
            env=env, capture_output=True,
        )
        if r.returncode == 0:
            print(f"[entrypoint] PostgreSQL ready via pg_isready (attempt {i})")
            sys.exit(0)
        print(f"[entrypoint] pg_isready not ready ({i}/{attempts})")
        time.sleep(interval)
    print("[entrypoint] Timed out waiting for PostgreSQL", file=sys.stderr)
    sys.exit(1)

# Fallback: raw TCP + asyncpg probe.
for i in range(1, attempts + 1):
    try:
        with socket.create_connection((host, port), timeout=3):
            pass
        try:
            import asyncio, asyncpg
            async def _ping():
                c = await asyncpg.connect(host=host, port=port, user=user,
                                          password=password or None,
                                          database=dbname, timeout=5)
                await c.close()
            asyncio.run(_ping())
        except ImportError:
            pass
        print(f"[entrypoint] PostgreSQL reachable (attempt {i})")
        sys.exit(0)
    except Exception as exc:
        print(f"[entrypoint] DB wait {i}/{attempts}: {exc}")
        time.sleep(interval)

print("[entrypoint] Timed out waiting for PostgreSQL", file=sys.stderr)
sys.exit(1)
PY
  ok "PostgreSQL is ready."
}

# ── 2. Wait for Redis ─────────────────────────────────────────────────────────
wait_for_redis() {
  log "Waiting for Redis (up to $((MAX_REDIS_ATTEMPTS * WAIT_INTERVAL))s)…"
  python - <<'PY'
import os, sys, time, socket
from urllib.parse import urlparse, unquote

url = os.environ.get("REDIS_URL") or os.environ.get("CELERY_BROKER_URL") or ""
if not url:
    print("[entrypoint] REDIS_URL / CELERY_BROKER_URL not set — skipping Redis wait")
    sys.exit(0)

parsed   = urlparse(url)
host     = parsed.hostname or "redis"
port     = parsed.port or 6379
password = unquote(parsed.password) if parsed.password else None
db_index = 0
if parsed.path and parsed.path.strip("/"):
    try:
        db_index = int(parsed.path.strip("/"))
    except ValueError:
        pass

attempts = int(os.environ.get("MAX_REDIS_ATTEMPTS", "30"))
interval = int(os.environ.get("WAIT_INTERVAL", "2"))

for i in range(1, attempts + 1):
    try:
        import redis as _redis
        client = _redis.Redis(host=host, port=port, password=password,
                              db=db_index, socket_connect_timeout=3, socket_timeout=3)
        if client.ping():
            print(f"[entrypoint] Redis ready (attempt {i})")
            sys.exit(0)
    except ImportError:
        # redis package missing — fall back to TCP probe.
        try:
            with socket.create_connection((host, port), timeout=3):
                print(f"[entrypoint] Redis TCP reachable (attempt {i}) — redis-py not installed, skipping PING")
                sys.exit(0)
        except Exception:
            pass
    except Exception as exc:
        print(f"[entrypoint] Redis wait {i}/{attempts}: {exc}")
    time.sleep(interval)

print("[entrypoint] Timed out waiting for Redis", file=sys.stderr)
sys.exit(1)
PY
  ok "Redis is ready."
}

# ── 3. Apply Alembic migrations ───────────────────────────────────────────────
run_migrations() {
  if [[ "${SKIP_MIGRATIONS}" == "true" ]]; then
    warn "SKIP_MIGRATIONS=true — skipping alembic upgrade head."
    return 0
  fi

  log "Running: alembic upgrade head…"
  if ! alembic upgrade head; then
    fail "alembic upgrade head failed. Fix migration errors before continuing."
  fi
  ok "Alembic migrations applied."
}

# ── 4. Seed initial data ──────────────────────────────────────────────────────
run_seed() {
  if [[ "${SKIP_SEED}" == "true" ]]; then
    warn "SKIP_SEED=true — skipping seed_initial_data."
    return 0
  fi

  local seed_script="scripts/seed_initial_data.py"
  if [[ ! -f "${seed_script}" ]]; then
    warn "Seed script not found at ${seed_script} — skipping."
    return 0
  fi

  log "Running: python ${seed_script}…"
  if ! python "${seed_script}"; then
    # Seed failures are non-fatal — the platform can still start with partial data.
    warn "seed_initial_data.py exited with an error. Platform will start anyway."
    warn "Re-run manually: docker compose exec backend python scripts/seed_initial_data.py"
  else
    ok "Initial data seed complete."
  fi
}

# ── 5. Exec CMD ───────────────────────────────────────────────────────────────
main() {
  wait_for_postgres
  wait_for_redis
  run_migrations
  run_seed

  log "Handing off to: $*"
  exec "$@"
}

main "$@"
