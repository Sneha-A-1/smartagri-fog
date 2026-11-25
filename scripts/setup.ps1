# SmartAgri-Fog: one-time setup (and re-run after every `git pull`).
# Usage, from the project folder:   .\scripts\setup.ps1
$ErrorActionPreference = "Stop"
Set-Location (Join-Path $PSScriptRoot "..")

Write-Host ""
Write-Host "[1/3] Installing Python packages with uv..." -ForegroundColor Cyan
uv sync
if ($LASTEXITCODE -ne 0) { throw "uv sync failed. Send the error above to Claude." }

Write-Host ""
Write-Host "[2/3] Installing and building the web interface with npm..." -ForegroundColor Cyan
Push-Location apps/web
try {
    npm install --no-audit --no-fund
    if ($LASTEXITCODE -ne 0) { throw "npm install failed." }
    npm run build
    if ($LASTEXITCODE -ne 0) { throw "Building the web interface failed." }
} finally {
    Pop-Location
}

Write-Host ""
Write-Host "[3/3] Preparing settings..." -ForegroundColor Cyan
if (-not (Test-Path ".env")) {
    Copy-Item ".env.example" ".env"
    Write-Host "Created .env from .env.example (edit it to move results to another drive)."
} else {
    Write-Host ".env already exists; left unchanged."
}

Write-Host ""
Write-Host "Setup complete. Start the platform with:  .\scripts\start.ps1" -ForegroundColor Green
