@echo off
setlocal
cd /d "%~dp0..\.."

wslc version >nul 2>&1
if errorlevel 1 (
  echo WSL containers are not available. In PowerShell, run "wsl --update", then check "wslc version".
  echo WSL 2.9.3 or newer is required.
  pause
  exit /b 1
)

if not defined PORT set "PORT=8001"
if not exist data mkdir data
if not exist workspace mkdir workspace
if not exist tmp mkdir tmp

rem Already running (e.g. in another window)? Just open it instead of failing on the name conflict.
wslc ps 2>nul | findstr /C:"pokosomo-studio" >nul
if not errorlevel 1 (
  echo Pokosomo Studio is already running at http://localhost:%PORT%
  echo Opening it in your browser. To stop it, double-click windows\stop.bat.
  start "" "http://localhost:%PORT%"
  pause
  exit /b 0
)
rem Remove a leftover stopped container with the same name (ignore errors if there is none).
wslc rm pokosomo-studio >nul 2>&1

echo Starting Pokosomo Studio at http://localhost:%PORT%
echo The first run downloads the ready-made image and may take a while.
wslc image pull where22/pokosomo-zero:latest
if errorlevel 1 (
  echo Could not download the Pokosomo image. Check your internet connection and try again.
  pause
  exit /b 1
)
echo Keep this window open while using the studio. Press Ctrl+C to stop.
echo Your browser will open in a few seconds. If this is your first run, set the password below first.
start "" /min cmd /c "timeout /t 10 /nobreak >nul & start http://localhost:%PORT%"
wslc run --rm -it --name pokosomo-studio -p 127.0.0.1:%PORT%:8001 -e HOST=0.0.0.0 -e PORT=8001 -e POKOSOMO_VENV=/opt/venv -e POKOSOMO_SECRETS=/app/data/secrets.json -e CODEX_HOME=/root/.codex-auth -e CLAUDE_CONFIG_DIR=/root/.claude-auth -v "%CD%\workspace:/app/workspace" -v "%CD%\tmp:/app/tmp" -v "%CD%\data:/app/data" -v pokosomo-codex-auth:/root/.codex-auth -v pokosomo-claude-auth:/root/.claude-auth -v pokosomo-gemini-auth:/root/.gemini where22/pokosomo-zero:latest
if errorlevel 1 (
  echo Pokosomo did not start. Check the message above and try again.
  pause
  exit /b 1
)
endlocal
