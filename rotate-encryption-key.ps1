#Requires -Version 5.1
<#
.SYNOPSIS
  Rotate CREDENTIALS_ENCRYPTION_KEY in .env.production without orphaning secrets.

.DESCRIPTION
  Moves the currently active key into the read-only retired list and installs a
  freshly generated 32-byte key as active, for both crypto paths:

    app.core.crypto        CREDENTIALS_ENCRYPTION_KEY + CREDENTIALS_ENCRYPTION_KEYS_OLD
    services.crypto_service  KMS_KEYS (version map) + CREDENTIALS_KEY_VERSION

  Existing rows stay readable, so the app keeps working while
  backend/scripts/reencrypt_credentials.py migrates them onto the new key.
  Key material is never written to stdout.

  Note: PowerShell 5.1 reads .ps1 as ANSI, so keep this file ASCII-only.

.EXAMPLE
  .\rotate-encryption-key.ps1
  .\rotate-encryption-key.ps1 -NewKey "base64-32-bytes="
#>
param(
  [string]$EnvFile = ".env.production",
  [string]$NewKey
)

$ErrorActionPreference = "Stop"

if (-not (Test-Path $EnvFile)) {
  throw "$EnvFile not found. Run from the repo root."
}

if (-not $NewKey) {
  $bytes = New-Object byte[] 32
  [System.Security.Cryptography.RandomNumberGenerator]::Create().GetBytes($bytes)
  $NewKey = [Convert]::ToBase64String($bytes)
}

if ([Convert]::FromBase64String($NewKey).Length -ne 32) {
  throw "NewKey must decode to exactly 32 bytes."
}

$lines = Get-Content $EnvFile

function Get-EnvValue([string]$name) {
  $match = $lines | Where-Object { $_ -match "^\s*$name\s*=" } | Select-Object -Last 1
  if (-not $match) { return $null }
  return ($match -replace "^\s*$name\s*=", "").Trim().Trim('"').Trim("'")
}

$currentKey = Get-EnvValue "CREDENTIALS_ENCRYPTION_KEY"
if (-not $currentKey) { $currentKey = Get-EnvValue "ENCRYPTION_KEY" }
if (-not $currentKey) {
  throw "No CREDENTIALS_ENCRYPTION_KEY / ENCRYPTION_KEY found in $EnvFile."
}
if ($currentKey -eq $NewKey) {
  throw "New key is identical to the current key - nothing to rotate."
}

# Preserve any keys already retired by a previous rotation, plus every KMS_KEYS
# value (channel tokens historically used CREDENTIALS_ENCRYPTION_KEY while the
# vault kept older KEKs only in KMS_KEYS).
$existingRetired = Get-EnvValue "CREDENTIALS_ENCRYPTION_KEYS_OLD"
$retiredList = @($currentKey)
if ($existingRetired) {
  foreach ($entry in $existingRetired.Split(",")) {
    $trimmed = $entry.Trim()
    if ($trimmed -and $trimmed -ne $NewKey -and $retiredList -notcontains $trimmed) {
      $retiredList += $trimmed
    }
  }
}
$existingKmsForRetired = Get-EnvValue "KMS_KEYS"
if ($existingKmsForRetired) {
  try {
    $parsedRetired = $existingKmsForRetired | ConvertFrom-Json
    foreach ($prop in $parsedRetired.PSObject.Properties) {
      $trimmed = [string]$prop.Value
      if ($trimmed -and $trimmed -ne $NewKey -and $retiredList -notcontains $trimmed) {
        $retiredList += $trimmed
      }
    }
  } catch {
    Write-Warning "Existing KMS_KEYS is not valid JSON - skipped while building retired list."
  }
}

$previousVersion = Get-EnvValue "CREDENTIALS_KEY_VERSION"
if (-not $previousVersion) { $previousVersion = "1" }
$nextVersion = [int]$previousVersion + 1

# KMS_KEYS maps every version that still has rows to its key material.
$kmsEntries = @()
$existingKms = Get-EnvValue "KMS_KEYS"
if ($existingKms) {
  try {
    $parsed = $existingKms | ConvertFrom-Json
    foreach ($prop in $parsed.PSObject.Properties) {
      $kmsEntries += '"{0}":"{1}"' -f $prop.Name, $prop.Value
    }
  } catch {
    Write-Warning "Existing KMS_KEYS is not valid JSON - rebuilding from scratch."
  }
}
if (-not $kmsEntries) {
  $kmsEntries += '"{0}":"{1}"' -f $previousVersion, $currentKey
}
$kmsEntries += '"{0}":"{1}"' -f $nextVersion, $NewKey
$kmsJson = "{" + ($kmsEntries -join ",") + "}"

$updates = [ordered]@{
  "CREDENTIALS_ENCRYPTION_KEY"      = $NewKey
  "ENCRYPTION_KEY"                  = $NewKey
  "CREDENTIALS_ENCRYPTION_KEYS_OLD" = ($retiredList -join ",")
  "KMS_KEYS"                        = $kmsJson
  "CREDENTIALS_KEY_VERSION"         = "$nextVersion"
}

$backup = "$EnvFile.bak-$(Get-Date -Format 'yyyyMMdd-HHmmss')"
Copy-Item $EnvFile $backup
Write-Host "Backed up $EnvFile -> $backup"

$result = New-Object System.Collections.Generic.List[string]
$seen = @{}
foreach ($line in $lines) {
  $replaced = $false
  foreach ($name in $updates.Keys) {
    if ($line -match "^\s*$name\s*=") {
      if (-not $seen.ContainsKey($name)) {
        $result.Add("$name=$($updates[$name])")
        $seen[$name] = $true
      }
      $replaced = $true
      break
    }
  }
  if (-not $replaced) { $result.Add($line) }
}

$appended = @()
foreach ($name in $updates.Keys) {
  if (-not $seen.ContainsKey($name)) {
    $appended += $name
    $result.Add("$name=$($updates[$name])")
  }
}

Set-Content -Path $EnvFile -Value $result -Encoding utf8

Write-Host ""
Write-Host "Rotation written to ${EnvFile}:"
Write-Host "  active key           : replaced (32 bytes, base64)"
Write-Host "  retired keys kept    : $($retiredList.Count)"
Write-Host "  vault key version    : $previousVersion -> $nextVersion"
if ($appended.Count -gt 0) {
  Write-Host "  newly added settings : $($appended -join ', ')"
}
Write-Host ""
Write-Host "Next steps:"
Write-Host "  1. docker compose -f docker-compose.prod.yml up -d --no-deps backend_api celery_worker"
Write-Host "  2. docker exec -i <backend> python - < backend/scripts/reencrypt_credentials.py --dry-run"
Write-Host "  3. same without --dry-run, then clear CREDENTIALS_ENCRYPTION_KEYS_OLD and stale KMS_KEYS versions"
Write-Host "  4. delete $backup once the rotation is confirmed"
