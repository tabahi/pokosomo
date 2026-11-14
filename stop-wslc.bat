@echo off
setlocal
wslc container stop pokosomo-studio
if errorlevel 1 (
  echo Pokosomo is already stopped, or WSL containers are unavailable.
  pause
  exit /b 1
)
echo Pokosomo Studio has stopped. Your projects and sign-ins are saved.
endlocal
