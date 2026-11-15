@echo off
setlocal

echo Choose which account to connect:
echo   1. Claude
echo   2. OpenAI Codex
echo   3. Antigravity (Google)
set /p choice="Enter 1, 2 or 3: "
if "%choice%"=="1" (
  wslc exec -it pokosomo-studio claude auth login
) else if "%choice%"=="2" (
  wslc exec -it pokosomo-studio codex login
) else if "%choice%"=="3" (
  echo.
  echo Antigravity opens next. To sign in:
  echo   1. Choose "Sign in" and open the link it shows in your browser.
  echo   2. Sign in with your Google account.
  echo   3. Paste the code, or the full address of the page you land on, back here and press Enter.
  echo   4. When it says you are signed in, type /exit and press Enter.
  echo.
  wslc exec -it pokosomo-studio agy
  goto :done
) else (
  echo Please enter 1, 2 or 3.
  pause
  exit /b 1
)
if errorlevel 1 (
  echo Sign-in failed. Make sure Pokosomo is running, then try again.
  pause
  exit /b 1
)
:done
echo.
echo Follow the sign-in instructions shown above. You can now choose this assistant in Studio Settings.
pause
endlocal
