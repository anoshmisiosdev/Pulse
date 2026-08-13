# Start the API for local development on Windows (PowerShell).
#
#   cd backend
#   .\dev.ps1
#
# Uses a throwaway SQLite file so no Postgres, Docker or `uv` is needed — the
# repo's .venv already has every dependency. Sets AUTH_DISABLED so the API serves
# its built-in demo tenant instead of demanding a Bearer token, which is what you
# want when the frontend has no VITE_SUPABASE_* configured. (Don't try to blank
# SUPABASE_URL instead: PowerShell deletes an env var when you assign "" to it,
# so the override disappears and .env's real value wins.)
#
# For the real Supabase-backed setup, run uvicorn directly instead.

param(
    [string]$Database = "sqlite+aiosqlite:///./dev.db",
    [int]$Port = 8000,
    [switch]$Fresh  # delete the SQLite file first for a clean slate
)

$ErrorActionPreference = "Stop"
Set-Location $PSScriptRoot

$python = Join-Path $PSScriptRoot ".venv\Scripts\python.exe"
if (-not (Test-Path $python)) {
    Write-Error "No .venv found at $python. Create it with: uv sync  (or python -m venv .venv; .\.venv\Scripts\pip install -e .)"
}

if ($Fresh -and $Database -like "sqlite*") {
    $file = ($Database -split "///")[-1]
    if (Test-Path $file) { Remove-Item $file -Force; Write-Host "Removed $file" -ForegroundColor Yellow }
}

$env:DATABASE_URL = $Database
$env:AUTH_DISABLED = "true"     # -> built-in demo tenant, no login required (dev only)

Write-Host "API      http://localhost:$Port  (docs at /docs)" -ForegroundColor Green
Write-Host "Database $Database" -ForegroundColor Green
Write-Host "Auth     demo tenant (no login)" -ForegroundColor Green
Write-Host ""

& $python -m uvicorn app.main:app --reload --port $Port
