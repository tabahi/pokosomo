@echo off
setlocal
cd /d "%~dp0"
docker compose down
if errorlevel 1 (
  echo Could not stop Pokosomo. Make sure Docker Desktop is running.
  pause
  exit /b 1
)
echo Pokosomo Studio has stopped. Your projects and sign-ins are saved.
pause
endlocal
