#Requires -Version 5.1
<#
.SYNOPSIS
  Installs, starts, and provisions local PostgreSQL for MP.AI development (Windows, no Docker).

.USAGE
  powershell -ExecutionPolicy Bypass -File .\scripts\setup-postgres-windows.ps1
  powershell -ExecutionPolicy Bypass -File .\scripts\setup-postgres-windows.ps1 -SkipInstall
#>
param(
    [string]$PostgresVersion = "16",
    [string]$DbName = "mpai",
    [string]$DbUser = "postgres",
    [string]$DbPassword = "postgres",
    [int]$Port = 5432,
    [switch]$SkipInstall
)

$ErrorActionPreference = "Stop"
$Root = Split-Path -Parent (Split-Path -Parent $MyInvocation.MyCommand.Path)
$Backend = Join-Path $Root "backend"
$Migrations = Join-Path $Backend "migrations"
$EnvFile = Join-Path $Backend ".env"

function Write-Step([string]$Message) {
    Write-Host "[setup-postgres] $Message" -ForegroundColor Cyan
}

function Find-PsqlPath {
    $candidates = @(
        "C:\Program Files\PostgreSQL\$PostgresVersion\bin\psql.exe",
        "C:\Program Files\PostgreSQL\17\bin\psql.exe",
        "C:\Program Files\PostgreSQL\16\bin\psql.exe",
        "C:\Program Files\PostgreSQL\15\bin\psql.exe"
    )
    foreach ($path in $candidates) {
        if (Test-Path $path) { return $path }
    }
    $cmd = Get-Command psql -ErrorAction SilentlyContinue
    if ($cmd) { return $cmd.Source }
    return $null
}

function Get-PostgresService {
    Get-Service -ErrorAction SilentlyContinue |
        Where-Object { $_.Name -like "postgresql*" -or $_.DisplayName -like "*PostgreSQL*" }
}

function Install-PostgreSQL {
    if ($SkipInstall) {
        Write-Step "Skipping winget install (-SkipInstall)."
        return
    }

    $psql = Find-PsqlPath
    if ($psql) {
        Write-Step "PostgreSQL binaries already present at $psql"
        return
    }

    Write-Step "Installing PostgreSQL $PostgresVersion via winget (requires admin)..."
    winget install "PostgreSQL.PostgreSQL.$PostgresVersion" `
        --accept-package-agreements `
        --accept-source-agreements `
        --disable-interactivity

    Start-Sleep -Seconds 5
}

function Start-PostgresService {
    $services = @(Get-PostgresService)
    if ($services.Count -eq 0) {
        throw "PostgreSQL Windows service not found. Complete the installer UI or rerun without -SkipInstall."
    }

    $service = $services | Sort-Object Name -Descending | Select-Object -First 1
    Write-Step "Using service: $($service.Name)"

    if ($service.Status -ne "Running") {
        Start-Service $service.Name
        Start-Sleep -Seconds 4
    }

    $deadline = (Get-Date).AddMinutes(2)
    while ((Get-Date) -lt $deadline) {
        $listener = Get-NetTCPConnection -LocalPort $Port -State Listen -ErrorAction SilentlyContinue
        if ($listener) { return }
        Start-Sleep -Seconds 2
    }

    throw "PostgreSQL is not listening on port $Port."
}

function Invoke-Psql([string]$PsqlPath, [string]$Sql, [string]$Database = "postgres") {
    $env:PGPASSWORD = $DbPassword
    & $PsqlPath -h 127.0.0.1 -p $Port -U $DbUser -d $Database -v ON_ERROR_STOP=1 -c $Sql
    if ($LASTEXITCODE -ne 0) {
        throw "psql failed: $Sql"
    }
}

function Invoke-PsqlFile([string]$PsqlPath, [string]$FilePath, [string]$Database = $DbName) {
    $env:PGPASSWORD = $DbPassword
    Get-Content -Raw -Path $FilePath | & $PsqlPath -h 127.0.0.1 -p $Port -U $DbUser -d $Database -v ON_ERROR_STOP=1
    if ($LASTEXITCODE -ne 0) {
        throw "Migration failed: $FilePath"
    }
}

function Ensure-Database {
    param([string]$PsqlPath)

    Write-Step "Provisioning role/database ($DbName)..."
    $env:PGPASSWORD = $DbPassword
    $dbExistsRaw = & $PsqlPath -h 127.0.0.1 -p $Port -U $DbUser -d postgres -tAc `
        "SELECT 1 FROM pg_database WHERE datname = '$DbName';"
    $dbExists = if ($null -eq $dbExistsRaw) { "" } else { $dbExistsRaw.Trim() }

    if ($dbExists -ne "1") {
        Invoke-Psql $PsqlPath "CREATE DATABASE $DbName OWNER $DbUser ENCODING 'UTF8' TEMPLATE template0;"
    }

    Invoke-Psql $PsqlPath "ALTER USER $DbUser WITH PASSWORD '$DbPassword';"
}

function Ensure-EnvFile {
    $databaseUrl = "postgresql+asyncpg://${DbUser}:${DbPassword}@127.0.0.1:${Port}/${DbName}"
    Write-Step "Writing backend .env DATABASE_URL..."

    if (Test-Path $EnvFile) {
        $content = Get-Content $EnvFile -Raw
        if ($content -match "(?m)^DATABASE_URL=") {
            $content = [regex]::Replace($content, "(?m)^DATABASE_URL=.*", "DATABASE_URL=$databaseUrl")
        } else {
            $content += "`nDATABASE_URL=$databaseUrl`n"
        }
        Set-Content -Path $EnvFile -Value $content -Encoding UTF8
    } else {
        @(
            "# Local MP.AI backend environment"
            "DATABASE_URL=$databaseUrl"
            "REDIS_URL=redis://127.0.0.1:6379/0"
            "CELERY_BROKER_URL=redis://127.0.0.1:6379/0"
            "CELERY_RESULT_BACKEND=redis://127.0.0.1:6379/0"
            "LOG_LEVEL=INFO"
            "OPERATOR_WS_TOKEN=dev-operator-token"
        ) | Set-Content -Path $EnvFile -Encoding UTF8
    }

    $env:DATABASE_URL = $databaseUrl
}

function Run-Bootstrap {
    Write-Step "Bootstrapping ORM schema (SQLAlchemy create_all)..."
    Push-Location $Backend
    try {
        $env:PYTHONPATH = $Backend
        python scripts/bootstrap_database.py
        if ($LASTEXITCODE -ne 0) { throw "bootstrap_database.py failed" }
    } finally {
        Pop-Location
    }
}

function Run-SqlMigrations {
    param([string]$PsqlPath)

    Write-Step "Applying SQL migrations..."
    Invoke-Psql $PsqlPath "CREATE TABLE IF NOT EXISTS schema_migrations (filename TEXT PRIMARY KEY, applied_at TIMESTAMPTZ NOT NULL DEFAULT NOW());" $DbName

    $files = Get-ChildItem -Path $Migrations -Filter "*.sql" | Sort-Object Name
    foreach ($file in $files) {
        $env:PGPASSWORD = $DbPassword
        $appliedRaw = & $PsqlPath -h 127.0.0.1 -p $Port -U $DbUser -d $DbName -tAc `
            "SELECT 1 FROM schema_migrations WHERE filename = '$($file.Name)' LIMIT 1;"
        $applied = if ($null -eq $appliedRaw) { "" } else { $appliedRaw.Trim() }
        if ($applied -eq "1") {
            Write-Step "Skip $($file.Name) (already applied)"
            continue
        }

        if ($file.Name -eq "001_core_platform_schema.sql") {
            Write-Step "Mark baseline $($file.Name) (tables created via bootstrap)"
            Invoke-Psql $PsqlPath "INSERT INTO schema_migrations (filename) VALUES ('$($file.Name)');" $DbName
            continue
        }

        Write-Step "Apply $($file.Name)"
        try {
            Invoke-PsqlFile $PsqlPath $file.FullName
        } catch {
            Write-Warning "Migration $($file.Name) skipped (schema likely already provisioned by bootstrap): $($_.Exception.Message)"
        }
        Invoke-Psql $PsqlPath "INSERT INTO schema_migrations (filename) VALUES ('$($file.Name)');" $DbName
    }
}

function Test-Health {
    Write-Step "Verifying API health endpoints..."
    Start-Sleep -Seconds 2

    $basic = Invoke-RestMethod -Uri "http://127.0.0.1:8000/healthcheck" -TimeoutSec 10
    Write-Host "  /healthcheck => $($basic | ConvertTo-Json -Compress)"

    try {
        $ready = Invoke-RestMethod -Uri "http://127.0.0.1:8000/api/v1/health/ready" -TimeoutSec 15
        Write-Host "  /api/v1/health/ready => status=$($ready.status) ready=$($ready.ready)"
        if (-not $ready.ready) {
            Write-Warning "Readiness probe not fully ready yet. Restart the backend to reload DATABASE_URL from .env"
        }
    } catch {
        Write-Warning "Readiness probe failed (restart backend if DATABASE_URL was just created): $($_.Exception.Message)"
    }
}

Write-Step "MP.AI local PostgreSQL setup starting..."
Install-PostgreSQL
$psql = Find-PsqlPath
if (-not $psql) {
    throw "psql not found. Install PostgreSQL and rerun, or add its bin folder to PATH."
}
Write-Step "Using psql: $psql"

Start-PostgresService
Ensure-Database -PsqlPath $psql
Ensure-EnvFile
Run-Bootstrap
Run-SqlMigrations -PsqlPath $psql
Test-Health

Write-Step "Done. Database '$DbName' is ready on 127.0.0.1:$Port"
Write-Step "If API still reports DB errors, restart uvicorn so it picks up backend/.env"
