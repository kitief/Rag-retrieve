# RagVault - local development
#
# EASIEST ENTRY POINT -- works regardless of PowerShell execution policy:
#   scripts\dev.cmd                 (see dev.cmd: it re-launches this file with
#   scripts\dev.cmd -BackendOnly     -ExecutionPolicy Bypass scoped to one child
#   scripts\dev.cmd -NoReload        process, because unsigned local scripts are
#   scripts\dev.cmd -Frozen          rejected on machines where RemoteSigned's
#   scripts\dev.cmd -Stop            Authenticode check is broken or locked down)
#
# Calling this file directly only works when your policy permits unsigned local
# scripts. If it does not, use dev.cmd or the explicit form below:
#
#   powershell -NoProfile -ExecutionPolicy Bypass -File .\scripts\dev.ps1
#   powershell -NoProfile -ExecutionPolicy Bypass -File .\scripts\dev.ps1 -BackendOnly
#   powershell -NoProfile -ExecutionPolicy Bypass -File .\scripts\dev.ps1 -NoReload
#   powershell -NoProfile -ExecutionPolicy Bypass -File .\scripts\dev.ps1 -Frozen
#   powershell -NoProfile -ExecutionPolicy Bypass -File .\scripts\dev.ps1 -Stop
#
# This runs the whole product as a single Python process -- the same process the
# Tauri shell spawns -- and adds the Vite dev server on top for hot module
# replacement. SQLite and the embedded Chroma store live under .desktop-data\
# in the repository.
#
# Use it for day-to-day work on the Python backend and the React frontend. Use
#   npm run tauri dev
# when you need the real desktop shell (native save dialog, first-run prompt),
# and src-tauri\target\release\bundle\nsis\* when you need the installer.
#
# NOTE: keep this file pure ASCII. Windows PowerShell 5.1 reads .ps1 files using
# the system ANSI code page unless they carry a BOM, so non-ASCII characters in
# string literals turn into mojibake at runtime.
#
# NOTE: [CmdletBinding()] makes an unrecognised switch a hard error. Without it
# a script with a param() block silently swallows unknown arguments into $args,
# so a typo like -BackendOnyl would quietly start the full two-server stack
# instead of only the API.
[CmdletBinding()]
param(
    [switch]$BackendOnly,
    [switch]$NoReload,
    [switch]$Frozen,
    [switch]$Stop,
    [int]$ApiPort = 8000,
    [int]$WebPort = 3000
)

$ErrorActionPreference = "Continue"

# Script lives in <repo>\scripts, so the repo root is one level up.
$repo = Split-Path $PSScriptRoot -Parent
if (-not (Test-Path (Join-Path $repo "backend\app\main.py"))) {
    Write-Host "ERROR: could not locate RagVault\backend\app\main.py from $repo" -ForegroundColor Red
    exit 1
}

function Stop-DevStack {
    # The uvicorn autoreloader forks a child that is the process actually
    # holding the socket, and vite runs as node. Match on command line instead
    # of on port so both halves die together.
    $killed = 0
    Get-CimInstance Win32_Process -Filter "Name like 'python%' or Name like 'ragvault%'" -ErrorAction SilentlyContinue |
        Where-Object { $_.CommandLine -and ($_.CommandLine -like '*run_desktop*' -or $_.CommandLine -like '*multiprocessing.spawn*' -or $_.CommandLine -like '*uvicorn*') } |
        ForEach-Object {
            Stop-Process -Id $_.ProcessId -Force -ErrorAction SilentlyContinue
            $killed++
        }
    Get-CimInstance Win32_Process -Filter "Name = 'node.exe'" -ErrorAction SilentlyContinue |
        Where-Object { $_.CommandLine -and $_.CommandLine -like '*vite*' } |
        ForEach-Object {
            Stop-Process -Id $_.ProcessId -Force -ErrorAction SilentlyContinue
            $killed++
        }
    Write-Host "[dev] stopped $killed process(es)" -ForegroundColor Yellow
}

if ($Stop) { Stop-DevStack; exit 0 }

# A previous run may still be holding the ports; starting twice would otherwise
# fail with a confusing "address already in use".
Stop-DevStack

$python = Join-Path $repo ".venv-desktop\Scripts\python.exe"
if (-not (Test-Path $python)) {
    Write-Host "ERROR: $python not found." -ForegroundColor Red
    Write-Host "Create it once with:" -ForegroundColor Yellow
    Write-Host "  python -m venv .venv-desktop" -ForegroundColor Yellow
    Write-Host "  .venv-desktop\Scripts\pip install -r backend\requirements.txt" -ForegroundColor Yellow
    exit 1
}
$dataDir = Join-Path $repo ".desktop-data"

if ($Frozen) {
    # Exercise the exact binary that ships inside the installer. No hot reload
    # is possible -- rebuild the bundle for that.
    $exe = Join-Path $repo "dist\ragvault-backend\ragvault-backend.exe"
    if (-not (Test-Path $exe)) {
        Write-Host "ERROR: $exe not found." -ForegroundColor Red
        Write-Host "Build it with:" -ForegroundColor Yellow
        Write-Host "  .venv-desktop\Scripts\pyinstaller.exe backend\ragvault-backend.spec --noconfirm --distpath dist --workpath build\pyinstaller" -ForegroundColor Yellow
        exit 1
    }
    Write-Host "[dev] frozen backend (no reload)" -ForegroundColor Cyan
    $backend = Start-Process -FilePath $exe -PassThru -NoNewWindow -ArgumentList @(
        "--port", "$ApiPort", "--data-dir", $dataDir
    )
} else {
    $pyArgs = @("scripts\run_desktop.py", "--port", "$ApiPort", "--data-dir", $dataDir)
    if (-not $NoReload) { $pyArgs += "--reload" }
    if ($NoReload) {
        Write-Host "[dev] backend: run_desktop.py (no reload)" -ForegroundColor Cyan
    } else {
        Write-Host "[dev] backend: run_desktop.py (reload on save)" -ForegroundColor Cyan
    }
    $backend = Start-Process -FilePath $python -PassThru -NoNewWindow -WorkingDirectory $repo -ArgumentList $pyArgs
}

# Wait for the API to answer before starting anything else, so the first page
# load does not flash a proxy error. Lexical analysis of a 321 MB bundle and the
# first FastEmbed load both happen here, hence the generous deadline.
$deadline = (Get-Date).AddSeconds(120)
$ready = $false
while ((Get-Date) -lt $deadline) {
    try {
        $null = Invoke-RestMethod -Uri "http://127.0.0.1:$ApiPort/health" -TimeoutSec 2
        $ready = $true
        break
    } catch {
        if ($backend.HasExited) { break }
        Start-Sleep -Milliseconds 700
    }
}
if (-not $ready) {
    Write-Host "ERROR: API did not answer on port $ApiPort." -ForegroundColor Red
    Write-Host "       Check the console output above; the backend likely crashed on startup." -ForegroundColor Yellow
    if (-not $backend.HasExited) { Stop-Process -Id $backend.Id -Force -ErrorAction SilentlyContinue }
    exit 1
}
Write-Host "[dev] API ready on http://127.0.0.1:$ApiPort" -ForegroundColor Green

if ($BackendOnly) {
    # The backend also serves the built SPA, so a static build is enough to
    # click through the real app without the dev server.
    Write-Host ""
    Write-Host "  Build the UI once, then the API serves it:" -ForegroundColor Green
    Write-Host "    cd frontend; npm run build" -ForegroundColor Green
    Write-Host "    http://127.0.0.1:$ApiPort/" -ForegroundColor Green
    Write-Host ""
    Write-Host "  Press Ctrl+C to stop." -ForegroundColor Yellow
    try {
        Wait-Process -Id $backend.Id
    } finally {
        Stop-DevStack
    }
    exit 0
}

$frontend = Join-Path $repo "frontend"
if (-not (Test-Path (Join-Path $frontend "node_modules"))) {
    Write-Host "[dev] installing frontend dependencies (first run only)..." -ForegroundColor Yellow
    Push-Location $frontend
    & npm.cmd install --registry https://registry.npmmirror.com
    Pop-Location
}

if ($ApiPort -ne 8000) {
    Write-Host ""
    Write-Host "  WARNING: vite.config.ts proxies /api to http://localhost:8000." -ForegroundColor Yellow
    Write-Host "           With -ApiPort $ApiPort the UI will not reach the API unless you" -ForegroundColor Yellow
    Write-Host "           edit that proxy target. Use 8000 for the full stack." -ForegroundColor Yellow
}
if ($WebPort -ne 3000) {
    Write-Host ""
    Write-Host "  NOTE: -WebPort $WebPort is not forwarded to vite (its port is pinned in" -ForegroundColor Yellow
    Write-Host "        vite.config.ts). Edit that file to change it." -ForegroundColor Yellow
}

Write-Host ""
Write-Host "  UI (hot reload)   http://127.0.0.1:3000" -ForegroundColor Green
Write-Host "  API               http://127.0.0.1:$ApiPort" -ForegroundColor Green
Write-Host "  API docs          http://127.0.0.1:$ApiPort/docs" -ForegroundColor Green
Write-Host "  Data dir          $dataDir" -ForegroundColor Green
Write-Host ""
Write-Host "  Press Ctrl+C to stop." -ForegroundColor Yellow
Write-Host ""

Push-Location $frontend
try {
    & npm.cmd run dev
} finally {
    Pop-Location
    Write-Host ""
    Write-Host "[dev] shutting down..." -ForegroundColor Yellow
    Stop-DevStack
}
