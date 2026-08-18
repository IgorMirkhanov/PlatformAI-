#!/usr/bin/env bash
# =============================================================================
# MP.AI — setup_env.sh
# Install deps + infra for local development (run from repo root).
# =============================================================================
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$ROOT"

echo ""
echo "============================================================"
echo "  MP.AI local environment setup"
echo "  Root: $ROOT"
echo "============================================================"
echo ""

need() {
  if ! command -v "$1" >/dev/null 2>&1; then
    echo "[ERROR] '$1' is not installed or not on PATH."
    exit 1
  fi
}

need docker
need npm
if command -v python3 >/dev/null 2>&1; then
  PY=python3
elif command -v python >/dev/null 2>&1; then
  PY=python
else
  echo "[ERROR] Python is not installed or not on PATH."
  exit 1
fi

# Prefer Docker Compose v2 plugin
if docker compose version >/dev/null 2>&1; then
  COMPOSE=(docker compose)
elif command -v docker-compose >/dev/null 2>&1; then
  COMPOSE=(docker-compose)
else
  echo "[ERROR] docker compose is not available."
  exit 1
fi

# --- 1) Docker infrastructure ---
echo "[1/5] Starting Docker infrastructure (postgres, redis, chromadb)..."
"${COMPOSE[@]}" up -d postgres redis chromadb
echo "✅ Docker infrastructure is up (Postgres :5432, Redis :6379, Chroma :8001)"

echo "    Waiting for Postgres to become healthy..."
tries=0
until "${COMPOSE[@]}" exec -T postgres pg_isready -U postgres -d mpai >/dev/null 2>&1; do
  tries=$((tries + 1))
  if [[ "$tries" -ge 30 ]]; then
    echo "[ERROR] Postgres did not become ready in time."
    exit 1
  fi
  sleep 2
done
echo "✅ Postgres is healthy"

# Canonical local DB is ``mpai`` (matches docker-compose POSTGRES_DB).
# Do not create a second undocumented database.
echo "✅ Database ready (mpai)"

# --- 2) Backend venv + deps ---
echo ""
echo "[2/5] Setting up Backend (venv + pip)..."
if [[ ! -f "$ROOT/backend/.env" && -f "$ROOT/backend/.env.example" ]]; then
  cp "$ROOT/backend/.env.example" "$ROOT/backend/.env"
  echo "✅ Created backend/.env from .env.example"
fi

cd "$ROOT/backend"
if [[ ! -x "venv/bin/python" ]]; then
  "$PY" -m venv venv
  echo "✅ Virtual environment created"
else
  echo "✅ Virtual environment already exists"
fi

# shellcheck disable=SC1091
source venv/bin/activate
python -m pip install --upgrade pip
pip install -r requirements.txt
echo "✅ Backend dependencies installed"

# --- 3) Alembic ---
echo ""
echo "[3/5] Applying database migrations (alembic upgrade head)..."
alembic upgrade head
echo "✅ Database migrations applied"
deactivate || true

# --- 4) Frontend ---
echo ""
echo "[4/5] Setting up Frontend (npm + Playwright)..."
cd "$ROOT/frontend"
if [[ ! -f ".env.local" && -f ".env.local.example" ]]; then
  cp ".env.local.example" ".env.local"
  echo "✅ Created frontend/.env.local from example"
fi
npm install
echo "✅ Frontend dependencies installed"
if npx playwright install; then
  echo "✅ Playwright browsers installed"
else
  echo "⚠️  Playwright browser install reported an issue (non-fatal for basic UI)"
fi

# --- 5) WhatsApp ---
echo ""
echo "[5/5] Setting up WhatsApp service..."
cd "$ROOT/whatsapp-service"
if [[ ! -f ".env" && -f ".env.example" ]]; then
  cp ".env.example" ".env"
  echo "✅ Created whatsapp-service/.env from example"
fi
npm install
echo "✅ WhatsApp service dependencies installed"

cd "$ROOT"
echo ""
echo "============================================================"
echo "✅ MP.AI setup complete!"
echo ""
echo "Next step: ./run_dev.sh"
echo "  API        http://localhost:8000"
echo "  Frontend   http://localhost:3000"
echo "  WhatsApp   http://localhost:3001"
echo "  ChromaDB   http://localhost:8001"
echo "============================================================"
echo ""
