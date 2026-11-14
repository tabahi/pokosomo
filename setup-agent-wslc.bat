@echo off
setlocal

echo Choose which account to connect:
echo   1. Claude
echo   2. OpenAI Codex
set /p choice="Enter 1 or 2: "
if "%choice%"=="1" (
  wslc exec -it pokosomo-studio claude auth login
) else if "%choice%"=="2" (
  wslc exec -it pokosomo-studio codex login
) else (
  echo Please enter 1 or 2.
  pause
  exit /b 1
)
if errorlevel 1 (
  echo Sign-in failed. Make sure Pokosomo is running, then try again.
  pause
  exit /b 1
)
echo.
echo Follow the sign-in instructions shown above. You can now choose this assistant in Studio Settings.
pause
endlocal
