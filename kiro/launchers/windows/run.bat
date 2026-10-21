@echo off
setlocal

where kiro-cli >nul 2>nul
if %ERRORLEVEL% neq 0 (
    if not exist "C:\Program Files\Kiro-Cli\kiro-cli.exe" (
        echo Kiro CLI not found. Installing via official installer (https://cli.kiro.dev/install.ps1)... >&2
        powershell -NoProfile -ExecutionPolicy Bypass -Command "irm https://cli.kiro.dev/install.ps1 | iex"
    )
    set "PATH=C:\Program Files\Kiro-Cli\;%PATH%"
)

kiro-cli.exe acp %*
