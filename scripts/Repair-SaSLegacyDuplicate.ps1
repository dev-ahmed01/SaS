# Safe one-time repair. No remote access and no Docker volume deletion.
$ErrorActionPreference = 'Stop'
Set-StrictMode -Version Latest
$root = Split-Path -Parent $PSScriptRoot
$api = Join-Path $root 'apps\api'
$python = Join-Path $api '.venv\Scripts\python.exe'
if (-not (Test-Path $python)) { throw "Missing apps\api\.venv Python" }
if (Get-NetTCPConnection -LocalAddress 127.0.0.1 -LocalPort 8001 -State Listen -ErrorAction SilentlyContinue) {
    throw "Stop the local API on port 8001 using Ctrl+C before repair"
}
Push-Location $api
try {
    & $python -c "from app.config import get_settings; from sqlalchemy.engine import make_url; s=get_settings(); u=make_url(s.database_url); assert s.app_env=='development' and u.drivername=='postgresql+psycopg' and u.host in ('127.0.0.1','localhost') and (u.port or 5432)==5432 and u.database=='sas_dev' and u.username=='sas_dev', 'STOP: not the local sas_dev database'; print('Verified local sas_dev target')"
    if ($LASTEXITCODE -ne 0) { throw "Database configuration differs; refused to repair" }
} finally { Pop-Location }
Push-Location $root
try {
    docker compose up -d db
    if ($LASTEXITCODE -ne 0) { throw "Local database failed to start" }
    $containerId = (docker compose ps -q db).Trim()
    if (-not $containerId) { throw "Local DB container not found" }
    $name = "sas-before-legacy-repair-$(Get-Date -Format 'yyyyMMdd-HHmmss').dump"
    $remoteBackup = "/tmp/$name"
    $backup = Join-Path ([Environment]::GetFolderPath('Desktop')) $name
    docker compose exec -T db pg_dump -U sas_dev -d sas_dev -Fc -f $remoteBackup
    if ($LASTEXITCODE -ne 0) { throw "STOP: backup failed" }
    docker compose exec -T db pg_restore -l $remoteBackup | Out-Null
    if ($LASTEXITCODE -ne 0) { throw "STOP: backup archive validation failed" }
    docker cp "${containerId}:$remoteBackup" $backup
    if ($LASTEXITCODE -ne 0) { throw "STOP: could not copy backup" }
    if ((Get-Item $backup).Length -lt 1024) { throw "STOP: backup file too small" }
    Write-Host "Verified PostgreSQL backup: $backup"
} finally { Pop-Location }
Push-Location $api
try {
    & $python -m app.repair_local_duplicate --backup $backup
    if ($LASTEXITCODE -ne 0) {
        throw "Repair refused/cancelled. Backup retained at $backup. No migration attempted."
    }
    & $python -m alembic upgrade head
    if ($LASTEXITCODE -ne 0) { throw "Migration failed. Backup retained at $backup" }
    & $python -m alembic current
    if ($LASTEXITCODE -ne 0) { throw "Could not verify final migration version" }
    Write-Host "SUCCESS: repair and migrations complete. Restart API :8001 and web :3002."
} finally { Pop-Location }
