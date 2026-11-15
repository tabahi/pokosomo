@echo off
setlocal
rem Picks the best available container engine: WSL containers (wslc) first, then Docker.
rem The real work is in wslc\stop.bat and docker\stop.bat.

rem If the studio was started with WSL containers, stop that one; otherwise fall through to Docker.
wslc version >nul 2>&1
if not errorlevel 1 (
  wslc ps 2>nul | findstr /C:"pokosomo-studio" >nul
  if not errorlevel 1 (
    wslc container stop pokosomo-studio >nul 2>&1
    echo Pokosomo Studio has stopped. Your projects and sign-ins are saved.
    pause
    exit /b 0
  )
)

where docker >nul 2>&1
if not errorlevel 1 (
  call "%~dp0docker\stop.bat"
  exit /b
)

echo Pokosomo needs a container engine, and none was found on this computer.
echo.
echo Easiest option: install Docker Desktop from
echo   https://www.docker.com/products/docker-desktop/
echo open it, wait until it says "Engine running", then double-click this file again.
echo.
echo Alternative: WSL containers. In PowerShell run "wsl --update", then check "wslc version"
echo (WSL 2.9.3 or newer is required).
pause
exit /b 1
