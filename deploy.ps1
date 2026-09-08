#Requires -Version 5.1
<#
.SYNOPSIS
  Windows-friendly production deploy for MP.AI (docker-compose.prod.yml).

.DESCRIPTION
  Mirrors deploy.sh rolling restart without requiring Git Bash/WSL.
  On existing Alembic DBs, SQL files under backend/migrations are marked
  applied (SKIP_SQL_MIGRATIONS equivalent) so they do not conflict with
  entrypoint alembic upgrade head.

.EXAMPLE
  .\deploy.ps1
  .\deploy.ps1 -VerifyOnly
  .\deploy.ps1 -SkipBuild
#>
param(
  [switch]$VerifyOnly,
  [switch]$SkipBuild
)

$ErrorActionPreference = "Stop"
Set-Location $PSScriptRoot

$EnvFile = ".env.production"
$ComposeFile = "docker-compose.prod.yml"

function Invoke-Compose {
  param([Parameter(ValueFromRemainingArguments = $true)][string[]]$ComposeArgs)
  & docker compose --env-file $EnvFile -f $ComposeFile @ComposeArgs
  if ($LASTEXITCODE -ne 0) { throw "docker compose failed: $($ComposeArgs -join ' ')" }
}

function Get-EnvValue([string]$Name) {
  $line = Select-String -Path $EnvFile -Pattern "^$Name=" | Select-Object -First 1
  if (-not $line) { throw "Missing $Name in $EnvFile" }
  return ($line.Line -split "=", 2)[1].Trim()
}

function Wait-Healthy([string]$Service, [int]$Attempts = 60) {
  for ($i = 1; $i -le $Attempts; $i++) {
    $cid = (Invoke-Compose ps -q $Service 2>$null | Select-Object -First 1)
    if ($cid) {
      $cid = $cid.ToString().Trim()
      $health = docker inspect --format='{{if .State.Health}}{{.State.Health.Status}}{{else}}{{.State.Status}}{{end}}' $cid 2>$null
      Write-Host "[deploy] $Service=$health ($i)"
      if ($health -eq "healthy") { return }
      if ($Service -eq "celery_worker" -and ($health -eq "running" -or $health -eq "healthy")) { return }
      if ($health -eq "exited" -or $health -eq "dead") {
        Invoke-Compose logs --tail 40 $Service
        throw "$Service died ($health)"
      }
    } else {
      Write-Host "[deploy] $Service missing ($i)"
    }
    Start-Sleep -Seconds 2
  }
  Invoke-Compose logs --tail 40 $Service
  throw "$Service did not become healthy"
}

function Assert-HttpOk([string]$Url, [int[]]$OkCodes = @(200)) {
  try {
    $r = Invoke-WebRequest -Uri $Url -UseBasicParsing -TimeoutSec 15
    if ($OkCodes -notcontains [int]$r.StatusCode) {
      throw "Unexpected $($r.StatusCode) for $Url"
    }
    Write-Host "[deploy] OK $($r.StatusCode) $Url"
  } catch {
    throw "FAIL $Url : $($_.Exception.Message)"
  }
}

function Invoke-Verify {
  Write-Host "[deploy] Verify readiness..."
  Assert-HttpOk "http://127.0.0.1/healthz"
  Assert-HttpOk "http://127.0.0.1/healthcheck"
  Assert-HttpOk "http://127.0.0.1/api/v1/health/live"
  Assert-HttpOk "http://127.0.0.1/"
  try {
    Invoke-WebRequest -Uri "http://127.0.0.1/api/v1/health/ready" -UseBasicParsing -TimeoutSec 10 | Out-Null
    Write-Host "[deploy] WARN: /api/v1/health/ready returned success without internal key (unexpected)"
  } catch {
    $code = 0
    if ($_.Exception.Response) { $code = [int]$_.Exception.Response.StatusCode }
    if ($code -eq 403) {
      Write-Host "[deploy] OK /api/v1/health/ready → 403 without internal key (expected)"
    } else {
      Write-Host "[deploy] WARN /api/v1/health/ready status=$code"
    }
  }
  $wa = Invoke-Compose exec -T whatsapp_service wget -qO- http://127.0.0.1:3001/health
  Write-Host "[deploy] WhatsApp: $wa"
  Invoke-Compose exec -T celery_worker celery -A app.core.celery_app inspect ping -t 8 | Out-Host
  Invoke-Compose ps
  Write-Host "[deploy] Platform readiness confirmed."
}

if (-not (Test-Path $EnvFile)) {
  throw "Missing $EnvFile. Copy .env.production.example and configure secrets."
}
docker info 2>$null | Out-Null
if ($LASTEXITCODE -ne 0) { throw "Docker daemon is not running. Start Docker Desktop first." }

if (-not (Test-Path ".\nginx\ssl\fullchain.pem") -or -not (Test-Path ".\nginx\ssl\privkey.pem")) {
  $allow = ""
  try { $allow = Get-EnvValue "ALLOW_SELF_SIGNED" } catch { $allow = "0" }
  if ($allow -ne "1") {
    throw "TLS pem missing under nginx/ssl. Set ALLOW_SELF_SIGNED=1 or provide certs."
  }
  Write-Host "[deploy] WARN: TLS pem missing; generate self-signed before nginx recreate (openssl)."
}

if ($VerifyOnly) {
  Invoke-Verify
  exit 0
}

if (-not $SkipBuild) {
  Write-Host "[deploy] Building images..."
  Invoke-Compose build --parallel backend_api frontend_app whatsapp_service celery_worker
}

Write-Host "[deploy] Starting data plane..."
Invoke-Compose up -d postgres redis chromadb
Wait-Healthy postgres 40
Wait-Healthy redis 40
Wait-Healthy chromadb 50

$pgUser = Get-EnvValue "POSTGRES_USER"
$pgDb = Get-EnvValue "POSTGRES_DB"
Invoke-Compose exec -T postgres psql -v ON_ERROR_STOP=1 -U $pgUser -d $pgDb `
  -c "CREATE TABLE IF NOT EXISTS schema_migrations (filename TEXT PRIMARY KEY, applied_at TIMESTAMPTZ NOT NULL DEFAULT NOW());" | Out-Null
Get-ChildItem "backend\migrations\*.sql" -ErrorAction SilentlyContinue | ForEach-Object {
  $name = $_.Name
  Invoke-Compose exec -T postgres psql -v ON_ERROR_STOP=1 -U $pgUser -d $pgDb `
    -c "INSERT INTO schema_migrations (filename) VALUES ('$name') ON CONFLICT DO NOTHING;" | Out-Null
}
Write-Host "[deploy] SQL migrations marked applied (Alembic/entrypoint is source of truth)."

foreach ($svc in @("backend_api", "whatsapp_service", "celery_worker", "frontend_app", "nginx")) {
  Write-Host "[deploy] Rolling recreate: $svc"
  Invoke-Compose up -d --no-deps --force-recreate $svc
  Wait-Healthy $svc 60
}

Invoke-Verify
Write-Host "[deploy] Deployment complete."
