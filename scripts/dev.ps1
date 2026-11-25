# SmartAgri-Fog: development mode. Code changes reload automatically.
# Opens the API in a second window and runs the web dev server in this one.
# Usage, from the project folder:   .\scripts\dev.ps1
# Then open http://localhost:5173
$ErrorActionPreference = "Stop"
$root = Resolve-Path (Join-Path $PSScriptRoot "..")
Set-Location $root

Start-Process powershell -ArgumentList "-NoExit", "-Command", "Set-Location '$root'; uv run smartagri-api --reload"
Write-Host "API starting in a new window. Web dev server starting here: http://localhost:5173" -ForegroundColor Green
Set-Location (Join-Path $root "apps/web")
npm run dev
