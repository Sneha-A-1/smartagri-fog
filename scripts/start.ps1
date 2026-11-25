# SmartAgri-Fog: start the platform and open it in your browser.
# Usage, from the project folder:   .\scripts\start.ps1
# Stop it with Ctrl+C in this window.
$ErrorActionPreference = "Stop"
Set-Location (Join-Path $PSScriptRoot "..")

if (-not (Test-Path "apps/web/dist/index.html")) {
    Write-Host "The web interface isn't built yet. Running setup first..." -ForegroundColor Yellow
    & (Join-Path $PSScriptRoot "setup.ps1")
}

$url = "http://127.0.0.1:8000"
Write-Host "Starting SmartAgri-Fog at $url  (press Ctrl+C to stop)" -ForegroundColor Green
Start-Job -ScriptBlock { param($u) Start-Sleep -Seconds 4; Start-Process $u } -ArgumentList $url | Out-Null
uv run smartagri-api
