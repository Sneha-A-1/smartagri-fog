# SmartAgri-Fog: start the platform and open it in your browser.
# Usage, from the project folder:   .\scripts\start.ps1
# Stop it with Ctrl+C in this window.
#
# Before starting, this script brings everything up to date with the code you have checked out:
# Python packages (uv sync) and, when the code changed since the last build, the web interface.
$ErrorActionPreference = "Stop"
Set-Location (Join-Path $PSScriptRoot "..")

Write-Host "Checking Python packages..." -ForegroundColor Cyan
uv sync --quiet
if ($LASTEXITCODE -ne 0) { throw "uv sync failed. Send the error above to Claude." }

$commit = (git rev-parse HEAD).Trim()
$stampFile = "apps/web/dist/.build-commit"
$built = if (Test-Path $stampFile) { (Get-Content $stampFile -Raw).Trim() } else { "" }
# Uncommitted edits to the interface (ignoring the lock file, which npm may rewrite) also trigger a rebuild.
$localChanges = [bool](git status --porcelain -- apps/web ":!apps/web/package-lock.json")

if (-not (Test-Path "apps/web/dist/index.html") -or $built -ne $commit -or $localChanges) {
    Write-Host "The code changed since the interface was last built. Rebuilding it (about a minute)..." -ForegroundColor Yellow
    Push-Location apps/web
    try {
        npm ci --no-audit --no-fund
        if ($LASTEXITCODE -ne 0) { throw "Installing web packages failed. Send the error above to Claude." }
        npm run build
        if ($LASTEXITCODE -ne 0) { throw "Building the web interface failed." }
    } finally {
        Pop-Location
    }
    Set-Content -Path $stampFile -Value $commit -NoNewline
} else {
    Write-Host "Web interface is up to date." -ForegroundColor Cyan
}

if (-not (Test-Path ".env")) { Copy-Item ".env.example" ".env" }

$short = $commit.Substring(0, 7)
$url = "http://127.0.0.1:8000"
Write-Host "Starting SmartAgri-Fog (version $short) at $url  (press Ctrl+C to stop)" -ForegroundColor Green
Start-Job -ScriptBlock { param($u) Start-Sleep -Seconds 4; Start-Process $u } -ArgumentList $url | Out-Null
uv run smartagri-api
