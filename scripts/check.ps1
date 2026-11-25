# SmartAgri-Fog: run every automated check (the same ones GitHub runs on each pull request).
# Usage, from the project folder:   .\scripts\check.ps1
$ErrorActionPreference = "Stop"
Set-Location (Join-Path $PSScriptRoot "..")

Write-Host "Python lint..." -ForegroundColor Cyan
uv run ruff check .
if ($LASTEXITCODE -ne 0) { throw "Lint failed" }
Write-Host "Python tests..." -ForegroundColor Cyan
uv run pytest
if ($LASTEXITCODE -ne 0) { throw "Python tests failed" }

Push-Location apps/web
try {
    Write-Host "Web type check..." -ForegroundColor Cyan
    npm run typecheck
    if ($LASTEXITCODE -ne 0) { throw "Type check failed" }
    Write-Host "Web tests..." -ForegroundColor Cyan
    npm test
    if ($LASTEXITCODE -ne 0) { throw "Web tests failed" }
} finally {
    Pop-Location
}
Write-Host "All checks passed." -ForegroundColor Green
