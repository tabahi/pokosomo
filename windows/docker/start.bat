@echo off
setlocal
cd /d "%~dp0..\.."

where docker >nul 2>&1
if errorlevel 1 (
  echo Docker Desktop is required. Install and start Docker Desktop, then try again.
  pause
  exit /b 1
)
docker info >nul 2>&1
if errorlevel 1 (
  echo Docker Desktop is not running yet. Start it, wait until it says "Engine running", then try again.
  pause
  exit /b 1
)

if not exist data mkdir data
if not exist workspace mkdir workspace
if not exist tmp mkdir tmp

echo Preparing Pokosomo Studio. The first download may take a while.
docker compose pull
if errorlevel 1 (
  echo The prebuilt image could not be pulled. Trying a local build instead.
  docker compose build
  if errorlevel 1 (
    echo Setup did not finish. Check the message above, then double-click windows\start.bat to try again.
    pause
    exit /b 1
  )
)

docker compose run --rm -T studio python -m server.auth status | findstr /C:"Login configured." >nul
if errorlevel 1 (
  echo.
  echo First, create your studio password. You will be asked whether to turn on two-factor sign-in.
  docker compose run --rm studio python -m server.auth setup
  if errorlevel 1 (
    echo Login setup did not finish. Double-click windows\start.bat to try again.
    pause
    exit /b 1
  )
)

echo.
echo Starting Pokosomo Studio in the background.
docker compose up -d
if errorlevel 1 (
  echo Pokosomo could not start. Check the message above, then make sure Docker Desktop is running and try again.
  pause
  exit /b 1
)

set "STUDIO_PORT=8001"
for /f "tokens=2 delims=:" %%P in ('docker compose port studio 8001 2^>nul') do set "STUDIO_PORT=%%P"
echo.
echo Opening Pokosomo Studio at http://localhost:%STUDIO_PORT%
echo You can close this window. To stop Pokosomo, double-click windows\stop.bat.
set "CONNECT=y"
set /p CONNECT="Connect your Claude, Codex or Antigravity account now? [Y/n]: "
if /i not "%CONNECT%"=="n" call "%~dp0setup-agent.bat"
start "" "http://localhost:%STUDIO_PORT%"
endlocal
