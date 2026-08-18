#!/bin/bash
# Production entrypoint for the Celery worker process.
# Waits for the Redis broker, then exec's Celery so SIGTERM/SIGINT reach the worker.
set -euo pipefail

export PYTHONPATH="/app${PYTHONPATH:+:$PYTHONPATH}"
cd /app

CELERY_LOG_LEVEL="$(echo "${LOG_LEVEL:-info}" | tr '[:upper:]' '[:lower:]')"
QUEUES="${CELERY_QUEUES:-${CELERY_INBOUND_QUEUE:-inbound_messages},${CELERY_CRM_QUEUE:-crm_actions}}"
CONCURRENCY="${CELERY_CONCURRENCY:-4}"
HOSTNAME="${CELERY_HOSTNAME:-celery@%h}"
MAX_BROKER_ATTEMPTS="${MAX_BROKER_ATTEMPTS:-60}"

log() {
  printf '[entrypoint-celery] %s\n' "$*"
}

wait_for_broker() {
  log "Waiting for Celery broker (${MAX_BROKER_ATTEMPTS} attempts)..."
  python - <<'PY'
import os
import socket
import sys
import time
from urllib.parse import urlparse, unquote

broker_url = os.environ.get("CELERY_BROKER_URL") or os.environ.get("REDIS_URL") or ""
if not broker_url:
    print("[entrypoint-celery] CELERY_BROKER_URL / REDIS_URL is not set", file=sys.stderr)
    sys.exit(1)

parsed = urlparse(broker_url)
scheme = (parsed.scheme or "redis").lower()
host = parsed.hostname or "redis"
port = parsed.port or (5672 if scheme.startswith("amqp") else 6379)
attempts = int(os.environ.get("MAX_BROKER_ATTEMPTS", "60"))

def redis_ready() -> bool:
    try:
        import redis

        password = unquote(parsed.password) if parsed.password else None
        db = 0
        if parsed.path and parsed.path.strip("/"):
            try:
                db = int(parsed.path.strip("/"))
            except ValueError:
                db = 0
        client = redis.Redis(
            host=host,
            port=port,
            password=password,
            db=db,
            socket_connect_timeout=3,
            socket_timeout=3,
        )
        return client.ping() is True
    except Exception:
        with socket.create_connection((host, port), timeout=3):
            return True

def amqp_ready() -> bool:
    with socket.create_connection((host, port), timeout=3):
        return True

for attempt in range(1, attempts + 1):
    try:
        ok = amqp_ready() if scheme.startswith("amqp") else redis_ready()
        if ok:
            print(f"[entrypoint-celery] Broker ready ({scheme}://{host}:{port}, attempt {attempt})")
            sys.exit(0)
    except Exception as exc:
        print(f"[entrypoint-celery] Broker wait {attempt}/{attempts}: {exc}")
    time.sleep(2)

print("[entrypoint-celery] Timed out waiting for broker", file=sys.stderr)
sys.exit(1)
PY
}

start_worker() {
  if [[ "$#" -gt 0 ]]; then
    log "Executing override command: $*"
    exec "$@"
  fi

  log "Starting Celery worker queues=${QUEUES} concurrency=${CONCURRENCY} hostname=${HOSTNAME}"
  exec celery -A app.core.celery_app worker \
    --loglevel="${CELERY_LOG_LEVEL}" \
    --hostname="${HOSTNAME}" \
    -Q "${QUEUES}" \
    -c "${CONCURRENCY}" \
    --max-tasks-per-child="${CELERY_MAX_TASKS_PER_CHILD:-200}" \
    --max-memory-per-child="${CELERY_MAX_MEMORY_PER_CHILD:-400000}"
}

wait_for_broker
start_worker "$@"
