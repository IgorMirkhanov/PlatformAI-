@echo off
setlocal EnableExtensions EnableDelayedExpansion
REM =============================================================================
REM MP.AI — setup_env.bat
REM Install deps + infra for local development (run from repo root).
REM =============================================================================

cd /d "%~dp0"
set "ROOT=%CD%"

echo.
echo ============================================================
echo   MP.AI local environment setup
echo   Root: %ROOT%
echo ============================================================
echo.

where docker >nul 2>&1
if errorlevel 1 (
  echo [ERROR] Docker is not installed or not on PATH.
  exit /b 1
)

where python >nul 2>&1
if errorlevel 1 (
  where py >nul 2>&1
  if errorlevel 1 (
    echo [ERROR] Python is not installed or not on PATH.
    exit /b 1
  )
  set "PY=py -3"
) else (
  set "PY=python"
)

where npm >nul 2>&1
if errorlevel 1 (
  echo [ERROR] npm / Node.js is not installed or not on PATH.
  exit /b 1
)

REM --- 1) Docker infrastructure (Postgres, Redis, ChromaDB only) ---
echo [1/5] Starting Docker infrastructure (postgres, redis, chromadb)...
docker compose up -d postgres redis chromadb
if errorlevel 1 (
  echo [ERROR] docker compose failed. Is Docker Desktop running?
  exit /b 1
)
echo ✅ Docker infrastructure is up (Postgres :5432, Redis :6379, Chroma :8001)

REM Wait for Postgres to accept connections
echo     Waiting for Postgres to become healthy...
set /a "_tries=0"
:wait_pg
set /a "_tries+=1"
docker compose exec -T postgres pg_isready -U postgres -d mpai >nul 2>&1
if errorlevel 1 (
  if !_tries! GEQ 30 (
    echo [ERROR] Postgres did not become ready in time.
    exit /b 1
  )
  timeout /t 2 /nobreak >nul
  goto wait_pg
)
echo ✅ Postgres is healthy

REM Canonical local DB is mpai (matches docker-compose POSTGRES_DB).
echo ✅ Database ready (mpai)

REM --- 2) Backend venv + deps ---
echo.
echo [2/5] Setting up Backend (venv + pip)...
if not exist "%ROOT%\backend\.env" (
  if exist "%ROOT%\backend\.env.example" (
    copy /Y "%ROOT%\backend\.env.example" "%ROOT%\backend\.env" >nul
    echo ✅ Created backend\.env from .env.example
  )
)

pushd "%ROOT%\backend"
if not exist "venv\Scripts\python.exe" (
  %PY% -m venv venv
  if errorlevel 1 (
    echo [ERROR] Failed to create virtualenv.
    popd
    exit /b 1
  )
  echo ✅ Virtual environment created
) else (
  echo ✅ Virtual environment already exists
)

call "venv\Scripts\activate.bat"
python -m pip install --upgrade pip
if errorlevel 1 (
  echo [ERROR] pip upgrade failed.
  popd
  exit /b 1
)
pip install -r requirements.txt
if errorlevel 1 (
  echo [ERROR] pip install -r requirements.txt failed.
  popd
  exit /b 1
)
echo ✅ Backend dependencies installed

REM --- 3) Alembic migrations ---
echo.
echo [3/5] Applying database migrations (alembic upgrade head)...
alembic upgrade head
if errorlevel 1 (
  echo [ERROR] alembic upgrade head failed. Check DATABASE_URL in backend\.env
  popd
  exit /b 1
)
echo ✅ Database migrations applied
popd

REM --- 4) Frontend ---
echo.
echo [4/5] Setting up Frontend (npm + Playwright)...
pushd "%ROOT%\frontend"
if not exist ".env.local" (
  if exist ".env.local.example" (
    copy /Y ".env.local.example" ".env.local" >nul
    echo ✅ Created frontend\.env.local from example
  )
)
call npm install
if errorlevel 1 (
  echo [ERROR] npm install failed in frontend.
  popd
  exit /b 1
)
echo ✅ Frontend dependencies installed
call npx playwright install
if errorlevel 1 (
  echo ⚠️  Playwright browser install reported an issue (non-fatal for basic UI)
) else (
  echo ✅ Playwright browsers installed
)
popd

REM --- 5) WhatsApp / Baileys service ---
echo.
echo [5/5] Setting up WhatsApp service...
pushd "%ROOT%\whatsapp-service"
if not exist ".env" (
  if exist ".env.example" (
    copy /Y ".env.example" ".env" >nul
    echo ✅ Created whatsapp-service\.env from example
  )
)
call npm install
if errorlevel 1 (
  echo [ERROR] npm install failed in whatsapp-service.
  popd
  exit /b 1
)
echo ✅ WhatsApp service dependencies installed
popd

echo.
echo ============================================================
echo ✅ MP.AI setup complete!
echo.
echo Next step: run_dev.bat
echo   API        http://localhost:8000
echo   Frontend   http://localhost:3000
echo   WhatsApp   http://localhost:3001
echo   ChromaDB   http://localhost:8001
echo ============================================================
echo.
endlocal
exit /b 0
