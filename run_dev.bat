@echo off
setlocal EnableExtensions
REM =============================================================================
REM MP.AI — run_dev.bat
REM Boot local infra + open terminals for API, Celery, Frontend, WhatsApp.
REM =============================================================================

cd /d "%~dp0"
set "ROOT=%CD%"

echo.
echo ============================================================
echo   MP.AI local development launcher
echo ============================================================
echo.

where docker >nul 2>&1
if errorlevel 1 (
  echo [ERROR] Docker is not installed or not on PATH.
  exit /b 1
)

if not exist "%ROOT%\backend\venv\Scripts\activate.bat" (
  echo [ERROR] Backend venv missing. Run setup_env.bat first.
  exit /b 1
)
if not exist "%ROOT%\frontend\node_modules" (
  echo [ERROR] Frontend deps missing. Run setup_env.bat first.
  exit /b 1
)
if not exist "%ROOT%\whatsapp-service\node_modules" (
  echo [ERROR] WhatsApp deps missing. Run setup_env.bat first.
  exit /b 1
)

echo [infra] Ensuring Docker services (postgres, redis, chromadb)...
docker compose up -d postgres redis chromadb
if errorlevel 1 (
  echo [ERROR] docker compose failed. Is Docker Desktop running?
  exit /b 1
)
echo ✅ Infrastructure is up
echo.

REM Celery on Windows needs --pool=solo (prefork is unsupported)
echo [launch] Opening service terminals...

start "MP.AI Backend (FastAPI :8000)" cmd /k cd /d "%ROOT%\backend" ^& call venv\Scripts\activate.bat ^& echo ✅ Backend venv active ^& uvicorn main:app --reload --host 0.0.0.0 --port 8000

start "MP.AI Celery Worker" cmd /k cd /d "%ROOT%\backend" ^& call venv\Scripts\activate.bat ^& echo ✅ Celery worker starting... ^& celery -A app.core.celery_app worker --loglevel=info --pool=solo -Q inbound_messages,crm_actions,celery

start "MP.AI Frontend (Next.js :3000)" cmd /k cd /d "%ROOT%\frontend" ^& echo ✅ Frontend starting... ^& npm run dev

start "MP.AI WhatsApp (Baileys :3001)" cmd /k cd /d "%ROOT%\whatsapp-service" ^& echo ✅ WhatsApp service starting... ^& npm run dev

echo.
echo 🚀 All MP.AI services have been launched! API: :8000 ^| Frontend: :3000
echo    WhatsApp: :3001 ^| ChromaDB: :8001 ^| Postgres: :5432 ^| Redis: :6379
echo.
echo Close the individual terminal windows to stop each service.
echo.
endlocal
exit /b 0
