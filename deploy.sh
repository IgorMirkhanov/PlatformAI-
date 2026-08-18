#!/usr/bin/env bash
# MP.AI production deploy — idempotent, multi-volume backup, rolling restart.
# Usage: ./deploy.sh | ./deploy.sh backup | migrate | verify | help
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$ROOT_DIR"

COMPOSE_FILE="docker-compose.prod.yml"
ENV_FILE=".env.production"
BACKUP_ROOT="${BACKUP_DIR:-${ROOT_DIR}/backups}"
BACKUP_RETENTION_DAYS="${BACKUP_RETENTION_DAYS:-14}"
COMPOSE=(docker compose --env-file "$ENV_FILE" -f "$COMPOSE_FILE")
RUN_STAMP="$(date -u +%Y%m%dT%H%M%SZ)"
BACKUP_RUN_DIR="${BACKUP_ROOT}/${RUN_STAMP}"

log()  { printf '[deploy] %s\n' "$*"; }
fail() { printf '[deploy] ERROR: %s\n' "$*" >&2; exit 1; }

require_command() {
  command -v "$1" >/dev/null 2>&1 || fail "Required command not found: $1"
}

compose() {
  "${COMPOSE[@]}" "$@"
}

service_running() {
  compose ps --status running --services 2>/dev/null | grep -qx "$1"
}

# ── Secrets validation (PRODUCTION_LAUNCH_CHECKLIST §2.2) ────────────────────
# JWT_SECRET_KEY is mandatory and must NOT equal ENCRYPTION_KEY /
# CREDENTIALS_ENCRYPTION_KEY. Compose has no JWT→encryption fallback.
REQUIRED_SECRETS=(
  POSTGRES_USER
  POSTGRES_PASSWORD
  POSTGRES_DB
  DATABASE_URL
  REDIS_PASSWORD
  REDIS_URL
  CELERY_BROKER_URL
  CELERY_RESULT_BACKEND
  OPERATOR_WS_TOKEN
  NEXT_PUBLIC_OPERATOR_WS_TOKEN
  WEBHOOK_BASE_URL
  CORS_ORIGINS
  MPAI_DOMAIN
  JWT_SECRET_KEY
  INTERNAL_SERVICE_API_KEY
)

assert_not_placeholder() {
  local name="$1" value="${2:-}"
  if [[ -z "$value" ]]; then
    fail "${name} is empty."
  fi
  if [[ "$value" == *"CHANGE_ME"* ]]; then
    fail "${name} still contains CHANGE_ME placeholder."
  fi
}

validate_secrets() {
  local name
  for name in "${REQUIRED_SECRETS[@]}"; do
    assert_not_placeholder "$name" "${!name:-}"
  done

  local enc="${ENCRYPTION_KEY:-${CREDENTIALS_ENCRYPTION_KEY:-}}"
  assert_not_placeholder "ENCRYPTION_KEY or CREDENTIALS_ENCRYPTION_KEY" "$enc"
  if [[ ${#enc} -lt 16 ]]; then
    fail "ENCRYPTION_KEY / CREDENTIALS_ENCRYPTION_KEY looks too short (<16)."
  fi

  assert_not_placeholder "JWT_SECRET_KEY" "${JWT_SECRET_KEY:-}"
  if [[ ${#JWT_SECRET_KEY} -lt 32 ]]; then
    fail "JWT_SECRET_KEY must be at least 32 characters."
  fi
  if [[ "${JWT_SECRET_KEY}" == "$enc" ]]; then
    fail "JWT_SECRET_KEY must be distinct from ENCRYPTION_KEY / CREDENTIALS_ENCRYPTION_KEY."
  fi

  assert_not_placeholder "INTERNAL_SERVICE_API_KEY" "${INTERNAL_SERVICE_API_KEY:-}"
  if [[ ${#INTERNAL_SERVICE_API_KEY} -lt 24 ]]; then
    fail "INTERNAL_SERVICE_API_KEY must be at least 24 characters."
  fi

  if [[ "${OPERATOR_WS_TOKEN}" != "${NEXT_PUBLIC_OPERATOR_WS_TOKEN}" ]]; then
    fail "OPERATOR_WS_TOKEN and NEXT_PUBLIC_OPERATOR_WS_TOKEN must match."
  fi

  if [[ ${#POSTGRES_PASSWORD} -lt 12 ]]; then
    fail "POSTGRES_PASSWORD must be at least 12 characters."
  fi
  if [[ ${#REDIS_PASSWORD} -lt 12 ]]; then
    fail "REDIS_PASSWORD must be at least 12 characters."
  fi
  if [[ ${#OPERATOR_WS_TOKEN} -lt 24 ]]; then
    fail "OPERATOR_WS_TOKEN must be at least 24 characters."
  fi

  if [[ "${DATABASE_URL}" != *"${POSTGRES_PASSWORD}"* ]]; then
    log "WARN: DATABASE_URL does not contain POSTGRES_PASSWORD — double-check credentials."
  fi
  if [[ "${REDIS_URL}" != *"${REDIS_PASSWORD}"* ]]; then
    log "WARN: REDIS_URL does not contain REDIS_PASSWORD — double-check credentials."
  fi
  if [[ "${WEBHOOK_BASE_URL}" != https://* && "${ENVIRONMENT:-production}" == "production" ]]; then
    log "WARN: WEBHOOK_BASE_URL should be https:// in production."
  fi

  if [[ -n "${GRAFANA_ADMIN_PASSWORD:-}" && "${GRAFANA_ADMIN_PASSWORD}" == *"CHANGE_ME"* && "${ENABLE_MONITORING:-0}" == "1" ]]; then
    fail "GRAFANA_ADMIN_PASSWORD still contains CHANGE_ME while ENABLE_MONITORING=1."
  fi

  export WHATSAPP_SERVICE_URL="${WHATSAPP_SERVICE_URL:-http://whatsapp_service:3001}"
  export WHATSAPP_SERVICE_WS_URL="${WHATSAPP_SERVICE_WS_URL:-ws://whatsapp_service:3001}"
  export WHATSAPP_FASTAPI_WEBHOOK_URL="${WHATSAPP_FASTAPI_WEBHOOK_URL:-http://backend_api:8000/api/v1/webhooks/whatsapp-qr}"
  export LOG_FORMAT="${LOG_FORMAT:-json}"
  export ENVIRONMENT="${ENVIRONMENT:-production}"
}

ensure_tls_material() {
  local cert="${SSL_CERT_PATH:-./nginx/ssl/fullchain.pem}"
  local key="${SSL_KEY_PATH:-./nginx/ssl/privkey.pem}"
  mkdir -p "$(dirname "$cert")" "$(dirname "$key")" ./nginx/certbot

  if [[ -f "$cert" && -f "$key" ]]; then
    log "TLS certificates present."
    return 0
  fi

  if [[ "${ALLOW_SELF_SIGNED:-0}" != "1" ]]; then
    fail "TLS files missing (${cert}, ${key}). Set SSL_* paths or ALLOW_SELF_SIGNED=1 for bootstrap only."
  fi

  require_command openssl
  log "WARN: Generating SELF-SIGNED TLS cert for bootstrap (domain=${MPAI_DOMAIN})."
  log "WARN: Do NOT leave ALLOW_SELF_SIGNED=1 in production — replace with Let's Encrypt ASAP."
  openssl req -x509 -nodes -newkey rsa:2048 -days 825 \
    -keyout "$key" \
    -out "$cert" \
    -subj "/CN=${MPAI_DOMAIN}" \
    -addext "subjectAltName=DNS:${MPAI_DOMAIN},DNS:localhost" 2>/dev/null \
    || openssl req -x509 -nodes -newkey rsa:2048 -days 825 \
      -keyout "$key" \
      -out "$cert" \
      -subj "/CN=${MPAI_DOMAIN}"
  chmod 600 "$key"
  log "Self-signed cert written. Replace with Let's Encrypt before public traffic."
}

load_env() {
  if [[ ! -f "$ENV_FILE" ]]; then
    fail "Missing ${ENV_FILE}. Copy .env.production.example and configure secrets."
  fi
  # Strip CR so a Windows-edited .env.production cannot poison secret values with \r.
  local normalized
  normalized="$(mktemp)"
  tr -d '\r' < "$ENV_FILE" > "$normalized"
  set -a
  # shellcheck disable=SC1090
  source "$normalized"
  set +a
  rm -f "$normalized"
  validate_secrets
  ensure_tls_material
}

# ── Backups (Postgres + Redis + Chroma + WhatsApp sessions) ──────────────────
backup_all() {
  mkdir -p "$BACKUP_RUN_DIR"
  log "Backup directory: ${BACKUP_RUN_DIR}"

  local any=0

  if service_running postgres; then
    any=1
    log "Backing up PostgreSQL..."
    if ! compose exec -T postgres \
      pg_dump -U "${POSTGRES_USER}" -d "${POSTGRES_DB}" --no-owner --format=plain \
      | gzip -c > "${BACKUP_RUN_DIR}/postgres.sql.gz"; then
      rm -f "${BACKUP_RUN_DIR}/postgres.sql.gz"
      fail "pg_dump failed — aborting deploy."
    fi
    [[ -s "${BACKUP_RUN_DIR}/postgres.sql.gz" ]] || fail "Empty postgres backup."
  else
    log "PostgreSQL not running — skip DB dump (first install)."
  fi

  if service_running redis; then
    any=1
    log "Backing up Redis (BGSAVE + RDB copy)..."
    compose exec -T redis redis-cli -a "${REDIS_PASSWORD}" --no-auth-warning BGSAVE >/dev/null 2>&1 || true
    sleep 2
    local redis_cid
    redis_cid="$(compose ps -q redis | head -1)"
    if [[ -n "$redis_cid" ]]; then
      docker cp "${redis_cid}:/data/dump.rdb" "${BACKUP_RUN_DIR}/redis-dump.rdb" 2>/dev/null \
        || log "WARN: could not copy Redis dump.rdb (may be empty on first boot)."
    fi
  fi

  if service_running chromadb; then
    any=1
    log "Backing up ChromaDB volume..."
    docker run --rm \
      -v mpai_chroma_data:/from:ro \
      -v "${BACKUP_RUN_DIR}:/to" \
      alpine:3.20 \
      sh -c 'cd /from && tar czf /to/chroma.tgz . 2>/dev/null || tar czf /to/chroma.tgz -C /from .' \
      || log "WARN: Chroma volume backup failed (volume may not exist yet)."
  fi

  # WhatsApp Baileys auth sessions — critical for QR continuity
  if docker volume inspect mpai_whatsapp_sessions >/dev/null 2>&1; then
    any=1
    log "Backing up WhatsApp sessions volume..."
    docker run --rm \
      -v mpai_whatsapp_sessions:/from:ro \
      -v "${BACKUP_RUN_DIR}:/to" \
      alpine:3.20 \
      sh -c 'cd /from && tar czf /to/whatsapp-sessions.tgz . 2>/dev/null || true' \
      || log "WARN: WhatsApp sessions backup skipped."
  else
    log "WhatsApp sessions volume not found yet — skip."
  fi

  printf '%s\n' "stamp=${RUN_STAMP}" "domain=${MPAI_DOMAIN}" "host=$(hostname 2>/dev/null || echo unknown)" \
    > "${BACKUP_RUN_DIR}/MANIFEST.txt"

  if [[ "$any" -eq 1 ]]; then
    log "Backup complete ($(du -sh "$BACKUP_RUN_DIR" | awk '{print $1}'))."
  else
    log "No running data services — empty backup stamp kept for audit."
  fi

  # Retention: remove old stamp directories
  find "$BACKUP_ROOT" -mindepth 1 -maxdepth 1 -type d -mtime "+${BACKUP_RETENTION_DAYS}" -exec rm -rf {} + 2>/dev/null || true
}

# ── Lifecycle helpers ────────────────────────────────────────────────────────
wait_healthy() {
  local service="$1"
  local attempts="${2:-45}"
  local i=0 cid health
  log "Waiting for ${service} to become healthy..."
  while true; do
    cid="$(compose ps -q "$service" 2>/dev/null | head -1 || true)"
    if [[ -n "$cid" ]]; then
      health="$(docker inspect --format='{{if .State.Health}}{{.State.Health.Status}}{{else}}{{.State.Status}}{{end}}' "$cid" 2>/dev/null || echo starting)"
      if [[ "$health" == "healthy" ]]; then
        log "${service} is healthy."
        return 0
      fi
      if [[ "$service" == "celery_worker" && ( "$health" == "running" || "$health" == "healthy" ) ]]; then
        log "${service} is ${health}."
        return 0
      fi
    else
      health="missing"
    fi
    i=$((i + 1))
    if [[ $i -ge $attempts ]]; then
      fail "${service} did not become healthy (last=${health})."
    fi
    sleep 2
  done
}

wait_postgres_ready() {
  local attempts=0
  until compose exec -T postgres \
    pg_isready -U "${POSTGRES_USER}" -d "${POSTGRES_DB}" >/dev/null 2>&1; do
    attempts=$((attempts + 1))
    [[ $attempts -lt 40 ]] || fail "PostgreSQL did not become ready in time."
    sleep 2
  done
}

graceful_stop_app_tier() {
  # Stop reverse-proxy + workers first so in-flight requests drain before API swap.
  log "Graceful stop of edge/workers (nginx → celery → frontend)..."
  compose stop nginx 2>/dev/null || true
  compose stop celery_worker 2>/dev/null || true
  compose stop frontend_app 2>/dev/null || true
}

ensure_migration_table() {
  compose exec -T postgres \
    psql -v ON_ERROR_STOP=1 -U "${POSTGRES_USER}" -d "${POSTGRES_DB}" <<'SQL'
CREATE TABLE IF NOT EXISTS schema_migrations (
    filename TEXT PRIMARY KEY,
    applied_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);
SQL
}

migration_applied() {
  local filename="$1"
  compose exec -T postgres \
    psql -tAc "SELECT 1 FROM schema_migrations WHERE filename = '${filename}' LIMIT 1;" \
    -U "${POSTGRES_USER}" -d "${POSTGRES_DB}" | grep -q 1
}

mark_migration_applied() {
  local filename="$1"
  compose exec -T postgres \
    psql -v ON_ERROR_STOP=1 -U "${POSTGRES_USER}" -d "${POSTGRES_DB}" \
    -c "INSERT INTO schema_migrations (filename) VALUES ('${filename}') ON CONFLICT DO NOTHING;"
}

run_migrations() {
  log "Bootstrapping ORM schema + Superadmin seed (idempotent)..."
  compose run --rm --no-deps backend_api python scripts/bootstrap_database.py
  ensure_migration_table

  if [[ "${SKIP_SQL_MIGRATIONS:-0}" == "1" ]]; then
    log "SKIP_SQL_MIGRATIONS=1 — marking SQL files applied without executing."
    shopt -s nullglob
    local migration_files=(backend/migrations/*.sql)
    shopt -u nullglob
    local migration
    for migration in $(printf '%s\n' "${migration_files[@]}" | sort); do
      mark_migration_applied "$(basename "$migration")"
    done
    return 0
  fi

  log "Applying tracked SQL migrations (idempotent)..."
  shopt -s nullglob
  local migration_files=(backend/migrations/*.sql)
  shopt -u nullglob
  local migration filename
  for migration in $(printf '%s\n' "${migration_files[@]}" | sort); do
    filename="$(basename "$migration")"
    if migration_applied "$filename"; then
      log "Skip applied: ${filename}"
      continue
    fi
    log "Running migration: ${filename}"
    if ! compose exec -T postgres \
      psql -v ON_ERROR_STOP=1 -U "${POSTGRES_USER}" -d "${POSTGRES_DB}" < "$migration"; then
      fail "Migration failed: ${filename} (restore from ${BACKUP_RUN_DIR})"
    fi
    mark_migration_applied "$filename"
  done
}

rolling_restart_apps() {
  log "Parallel image build (backend shared by API+Celery, frontend, whatsapp)..."
  compose build --parallel backend_api frontend_app whatsapp_service
  # Ensure celery image tag matches backend_api (same Dockerfile context).
  compose build celery_worker

  log "Starting / refreshing data plane..."
  compose up -d postgres redis chromadb
  wait_postgres_ready
  wait_healthy postgres 30
  wait_healthy redis 30
  wait_healthy chromadb 40

  backup_all
  run_migrations

  graceful_stop_app_tier

  log "Rolling restart: backend_api..."
  compose up -d --no-deps --force-recreate backend_api
  wait_healthy backend_api 60

  log "Rolling restart: whatsapp_service..."
  compose up -d --no-deps --force-recreate whatsapp_service
  wait_healthy whatsapp_service 45

  log "Rolling restart: celery_worker..."
  compose up -d --no-deps --force-recreate celery_worker
  wait_healthy celery_worker 40

  log "Rolling restart: frontend_app..."
  compose up -d --no-deps --force-recreate frontend_app
  wait_healthy frontend_app 60

  log "Reloading nginx edge..."
  compose up -d --no-deps --force-recreate nginx
  wait_healthy nginx 30

  if [[ "${ENABLE_MONITORING:-0}" == "1" ]]; then
    log "Starting monitoring profile..."
    compose --profile monitoring up -d prometheus grafana cadvisor
  fi
}

verify_readiness() {
  local attempts=0
  local failures=0

  check() {
    local name="$1"
    shift
    attempts=0
    log "Verify: ${name}..."
    until "$@" >/dev/null 2>&1; do
      attempts=$((attempts + 1))
      if [[ $attempts -ge 25 ]]; then
        log "FAIL: ${name}"
        failures=$((failures + 1))
        return 0
      fi
      sleep 3
    done
    log "OK: ${name}"
  }

  check "postgres" compose exec -T postgres pg_isready -U "${POSTGRES_USER}" -d "${POSTGRES_DB}"
  check "redis" compose exec -T redis redis-cli -a "${REDIS_PASSWORD}" --no-auth-warning ping
  check "chromadb" compose exec -T chromadb wget -qO- http://127.0.0.1:8000/api/v1/heartbeat
  check "backend /healthcheck" compose exec -T backend_api \
    python -c "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8000/healthcheck', timeout=5)"
  check "backend /api/v1/health/ready" compose exec -T backend_api \
    python -c "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8000/api/v1/health/ready', timeout=8)"
  check "whatsapp /health" compose exec -T whatsapp_service wget -qO- http://127.0.0.1:3001/health
  check "frontend /" compose exec -T frontend_app wget -qO- http://127.0.0.1:3000/
  check "nginx /healthz" compose exec -T nginx wget -qO- http://127.0.0.1/healthz
  check "celery inspect ping" compose exec -T celery_worker \
    celery -A app.core.celery_app inspect ping -t 5

  compose ps
  if [[ "$failures" -gt 0 ]]; then
    fail "Verify finished with ${failures} failure(s)."
  fi
  if [[ "${ALLOW_SELF_SIGNED:-0}" == "1" ]]; then
    log "!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!"
    log "WARN: ALLOW_SELF_SIGNED=1 — production is running a self-signed cert."
    log "WARN: Replace nginx/ssl/*.pem with Let's Encrypt and set ALLOW_SELF_SIGNED=0."
    log "!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!"
  fi
  log "Platform readiness confirmed for ${MPAI_DOMAIN}."
}

purge_stale_artifacts() {
  if [[ "${SKIP_PRUNE:-0}" == "1" ]]; then
    log "SKIP_PRUNE=1 — leaving builder cache intact."
    return 0
  fi
  log "Pruning stale builder cache / dangling images..."
  docker builder prune -af --filter "until=24h" || true
  docker image prune -af --filter "until=72h" || true
}

usage() {
  cat <<'EOF'
Usage: ./deploy.sh [command]

  (default)|deploy   Full idempotent deploy (backup → migrate → rolling restart → verify)
  backup             Snapshot Postgres + Redis + Chroma + WhatsApp sessions
  migrate            Backup + ORM bootstrap + SQL migrations
  verify             Health probes for all core services
  help               Show this message

Env flags:
  SKIP_PRUNE=1
  SKIP_SQL_MIGRATIONS=1
  ALLOW_SELF_SIGNED=0          (default; set 1 only for TLS bootstrap)
  ENABLE_MONITORING=1
  BACKUP_RETENTION_DAYS=14
  BACKUP_DIR=./backups
EOF
}

main() {
  require_command docker
  require_command gzip

  local cmd="${1:-deploy}"
  case "$cmd" in
    help|-h|--help) usage; exit 0 ;;
    backup)
      load_env
      compose up -d postgres redis chromadb 2>/dev/null || true
      wait_postgres_ready 2>/dev/null || true
      backup_all
      ;;
    migrate)
      load_env
      compose up -d postgres redis chromadb
      wait_postgres_ready
      backup_all
      compose build backend_api
      run_migrations
      ;;
    verify)
      load_env
      verify_readiness
      ;;
    deploy|"")
      load_env
      purge_stale_artifacts
      rolling_restart_apps
      verify_readiness
      log "Deployment complete. Domain: ${MPAI_DOMAIN} | Backup: ${BACKUP_RUN_DIR}"
      ;;
    *)
      fail "Unknown command: ${cmd}. Try ./deploy.sh help"
      ;;
  esac
}

main "$@"
