@echo off
setlocal
cd /d "%~dp0"

docker compose ps --status running --quiet studio >nul 2>&1
if errorlevel 1 (
  echo Start Pokosomo first by double-clicking start.bat, then run this shortcut.
  pause
  exit /b 1
)

echo Choose which account to connect:
echo   1. Claude
echo   2. OpenAI Codex
set /p choice="Enter 1 or 2: "
if "%choice%"=="1" (
  docker compose exec studio claude auth login
) else if "%choice%"=="2" (
  docker compose exec studio codex login
) else (
  echo Please enter 1 or 2.
  pause
  exit /b 1
)
echo.
echo Follow the sign-in instructions shown above. You can now choose this assistant in Studio Settings.
pause
endlocal
