#!/usr/bin/env bash
# =============================================================================
# MP.AI — run_dev.sh
# Boot local infra + start API, Celery, Frontend, WhatsApp in parallel.
# =============================================================================
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$ROOT"

echo ""
echo "============================================================"
echo "  MP.AI local development launcher"
echo "============================================================"
echo ""

if ! command -v docker >/dev/null 2>&1; then
  echo "[ERROR] Docker is not installed or not on PATH."
  exit 1
fi

if [[ ! -x "$ROOT/backend/venv/bin/python" ]]; then
  echo "[ERROR] Backend venv missing. Run ./setup_env.sh first."
  exit 1
fi
if [[ ! -d "$ROOT/frontend/node_modules" ]]; then
  echo "[ERROR] Frontend deps missing. Run ./setup_env.sh first."
  exit 1
fi
if [[ ! -d "$ROOT/whatsapp-service/node_modules" ]]; then
  echo "[ERROR] WhatsApp deps missing. Run ./setup_env.sh first."
  exit 1
fi

if docker compose version >/dev/null 2>&1; then
  COMPOSE=(docker compose)
elif command -v docker-compose >/dev/null 2>&1; then
  COMPOSE=(docker-compose)
else
  echo "[ERROR] docker compose is not available."
  exit 1
fi

echo "[infra] Ensuring Docker services (postgres, redis, chromadb)..."
"${COMPOSE[@]}" up -d postgres redis chromadb
echo "✅ Infrastructure is up"
echo ""

PIDS=()

cleanup() {
  echo ""
  echo "🛑 Stopping MP.AI app processes (infra containers left running)..."
  for pid in "${PIDS[@]:-}"; do
    if kill -0 "$pid" >/dev/null 2>&1; then
      kill "$pid" >/dev/null 2>&1 || true
      wait "$pid" 2>/dev/null || true
    fi
  done
  echo "✅ App processes stopped. (docker compose down — if you want infra off)"
}
trap cleanup EXIT INT TERM

LOG_DIR="$ROOT/.dev-logs"
mkdir -p "$LOG_DIR"

echo "[launch] Starting services in background (logs → $LOG_DIR)..."

(
  cd "$ROOT/backend"
  # shellcheck disable=SC1091
  source venv/bin/activate
  echo "✅ Backend starting (uvicorn :8000)"
  exec uvicorn main:app --reload --host 0.0.0.0 --port 8000
) >"$LOG_DIR/backend.log" 2>&1 &
PIDS+=($!)

(
  cd "$ROOT/backend"
  # shellcheck disable=SC1091
  source venv/bin/activate
  echo "✅ Celery worker starting"
  exec celery -A app.core.celery_app worker --loglevel=info -Q inbound_messages,crm_actions,celery
) >"$LOG_DIR/celery.log" 2>&1 &
PIDS+=($!)

(
  cd "$ROOT/frontend"
  echo "✅ Frontend starting (Next.js :3000)"
  exec npm run dev
) >"$LOG_DIR/frontend.log" 2>&1 &
PIDS+=($!)

(
  cd "$ROOT/whatsapp-service"
  echo "✅ WhatsApp service starting (:3001)"
  exec npm run dev
) >"$LOG_DIR/whatsapp.log" 2>&1 &
PIDS+=($!)

echo ""
echo "🚀 All MP.AI services have been launched! API: :8000 | Frontend: :3000"
echo "   WhatsApp: :3001 | ChromaDB: :8001 | Postgres: :5432 | Redis: :6379"
echo ""
echo "PIDs: ${PIDS[*]}"
echo "Tail logs:  tail -f $LOG_DIR/*.log"
echo "Stop:       Ctrl+C (leaves Docker infra running)"
echo ""

# Keep script alive until Ctrl+C; restart wait if a child exits early
while true; do
  for pid in "${PIDS[@]}"; do
    if ! kill -0 "$pid" >/dev/null 2>&1; then
      echo "[WARN] Process $pid exited — check logs in $LOG_DIR"
      # Remove dead pid from watch list
      NEW_PIDS=()
      for p in "${PIDS[@]}"; do
        if kill -0 "$p" >/dev/null 2>&1; then
          NEW_PIDS+=("$p")
        fi
      done
      PIDS=("${NEW_PIDS[@]}")
      if [[ "${#PIDS[@]}" -eq 0 ]]; then
        echo "[ERROR] All app processes exited."
        exit 1
      fi
      break
    fi
  done
  sleep 2
done
