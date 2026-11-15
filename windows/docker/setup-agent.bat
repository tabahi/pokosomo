@echo off
setlocal
cd /d "%~dp0..\.."

docker compose ps --status running --quiet studio >nul 2>&1
if errorlevel 1 (
  echo Start Pokosomo first by double-clicking windows\start.bat, then run this shortcut.
  pause
  exit /b 1
)

echo Choose which account to connect:
echo   1. Claude
echo   2. OpenAI Codex
echo   3. Antigravity (Google)
set /p choice="Enter 1, 2 or 3: "
if "%choice%"=="1" (
  docker compose exec studio claude auth login
) else if "%choice%"=="2" (
  docker compose exec studio codex login
) else if "%choice%"=="3" (
  echo.
  echo Antigravity opens next. To sign in:
  echo   1. Choose "Sign in" and open the link it shows in your browser.
  echo   2. Sign in with your Google account.
  echo   3. Paste the code, or the full address of the page you land on, back here and press Enter.
  echo   4. When it says you are signed in, type /exit and press Enter.
  echo.
  docker compose exec studio agy
) else (
  echo Please enter 1, 2 or 3.
  pause
  exit /b 1
)
echo.
echo Follow the sign-in instructions shown above. You can now choose this assistant in Studio Settings.
pause
endlocal
