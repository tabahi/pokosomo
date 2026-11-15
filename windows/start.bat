@echo off
setlocal
rem Picks the best available container engine: WSL containers (wslc) first, then Docker.
rem The real work is in wslc\start.bat and docker\start.bat.

rem One-time user agreement. The answer is remembered in data\ so it is only asked once.
if exist "%~dp0..\data\.terms-accepted" goto :engine
echo ==========================================================
echo   Pokosomo Studio - user agreement
echo ==========================================================
echo Pokosomo Studio is free software under the MIT License, see the LICENSE file.
echo.
echo It is provided "AS IS", WITHOUT WARRANTY OF ANY KIND. The authors give no guarantees
echo and accept no responsibility or liability for any damage, data loss, costs or other
echo consequences of using it, including anything the AI assistants do on your computer,
echo with your files or with your accounts.
echo.
echo You are responsible for your data, for your AI provider accounts and their terms of use,
echo and for keeping the studio secure, for example turning on two-factor sign-in on a public server.
echo.
set "AGREE="
set /p AGREE="Do you accept these terms? [y/N]: "
if /i "%AGREE%"=="y" goto :accepted
if /i "%AGREE%"=="yes" goto :accepted
echo You did not accept the terms, so nothing was installed.
pause
exit /b 1

:accepted
if not exist "%~dp0..\data" mkdir "%~dp0..\data"
> "%~dp0..\data\.terms-accepted" echo accepted %DATE% %TIME%
echo.

:engine

wslc version >nul 2>&1
if not errorlevel 1 (
  call "%~dp0wslc\start.bat"
  exit /b
)

where docker >nul 2>&1
if not errorlevel 1 (
  call "%~dp0docker\start.bat"
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
