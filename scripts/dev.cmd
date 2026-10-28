@echo off
REM ============================================================================
REM  RagVault - local development launcher
REM
REM  Why this file exists
REM  --------------------
REM  dev.ps1 is not code-signed. On machines whose PowerShell execution policy
REM  is RemoteSigned or AllSigned -- and especially on managed/corporate images
REM  where the Authenticode verification path itself is restricted -- running
REM    .\scripts\dev.ps1
REM  directly dies with
REM    "cannot be loaded because running scripts is disabled on this system"
REM  or "AuthorizationManager check failed".
REM
REM  A .cmd wrapper sidesteps that entirely: it is not a PowerShell script, so
REM  the execution policy never applies to it. It re-launches PowerShell with
REM  -ExecutionPolicy Bypass scoped to that single child process. Nothing is
REM  changed machine-wide, no registry key is touched, and the policy reverts as
REM  soon as the child exits.
REM
REM  Usage is identical to dev.ps1 -- every argument is forwarded verbatim:
REM
REM    scripts\dev.cmd                 REM API + Vite, both hot reloading
REM    scripts\dev.cmd -BackendOnly    REM API only (also serves the built SPA)
REM    scripts\dev.cmd -NoReload       REM disable reload; use with breakpoints
REM    scripts\dev.cmd -Frozen         REM run the PyInstaller bundle
REM    scripts\dev.cmd -Stop           REM stop every related process
REM    scripts\dev.cmd -ApiPort 8080
REM
REM  Keep this file pure ASCII and CRLF-terminated.
REM ============================================================================

setlocal

set "SCRIPT=%~dp0dev.ps1"

if not exist "%SCRIPT%" (
    echo ERROR: dev.ps1 not found next to this wrapper.
    echo        Expected: "%SCRIPT%"
    exit /b 1
)

REM Prefer the Windows PowerShell that ships with the OS. It is the version
REM dev.ps1 was written and tested against; PowerShell 7 is not required.
REM Resolve via %%~$PATH:I -- a bare `if exist "powershell.exe"` would test the
REM *current directory*, not PATH, and fail whenever the cwd is not System32.
set "PS="
for %%I in (powershell.exe) do if not "%%~$PATH:I"=="" set "PS=%%~$PATH:I"
if not defined PS set "PS=%SystemRoot%\System32\WindowsPowerShell\v1.0\powershell.exe"
if not exist "%PS%" (
    echo ERROR: could not find powershell.exe.
    exit /b 1
)

"%PS%" -NoProfile -ExecutionPolicy Bypass -File "%SCRIPT%" %*
set "RC=%ERRORLEVEL%"

endlocal & exit /b %RC%
