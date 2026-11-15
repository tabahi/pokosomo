@echo off
setlocal
rem Picks the best available container engine: WSL containers (wslc) first, then Docker.
rem The real work is in wslc\setup-agent.bat and docker\setup-agent.bat.

set "WSLC=0"
wslc version >nul 2>&1
if not errorlevel 1 set "WSLC=1"

rem If the studio is running in a WSL container, use that one.
if "%WSLC%"=="1" (
  wslc ps 2>nul | findstr /C:"pokosomo-studio" >nul
  if not errorlevel 1 (
    call "%~dp0wslc\setup-agent.bat"
    exit /b
  )
)

where docker >nul 2>&1
if not errorlevel 1 (
  call "%~dp0docker\setup-agent.bat"
  exit /b
)

if "%WSLC%"=="1" (
  call "%~dp0wslc\setup-agent.bat"
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
