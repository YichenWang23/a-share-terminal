@echo off
setlocal EnableExtensions
cd /d "%~dp0"
set "PORT=8770"
set "URL=http://127.0.0.1:%PORT%/"

rem ---------- 1) pick a real Python (never the Store alias) ----------
set "PYRUN="
set "PYW="
py -3 -c "import sys" >nul 2>nul
if not errorlevel 1 set "PYRUN=py -3"
if not defined PYRUN (
  python -c "import sys" >nul 2>nul
  if not errorlevel 1 set "PYRUN=python"
)
if not defined PYRUN goto :no_python
if exist "%SystemRoot%\pyw.exe" set "PYW=pyw -3"

rem ---------- 1.5) make sure a desktop icon exists (idempotent) ----------
%PYRUN% tools\\make_shortcut.py >nul 2>nul

rem ---------- 2) is the engine already up? ----------
powershell -NoProfile -ExecutionPolicy Bypass -Command "try{(New-Object Net.WebClient).DownloadString('%URL%api/health')|Out-Null;exit 0}catch{exit 1}" >nul 2>nul
if not errorlevel 1 goto :open_app

rem ---------- 3) start the engine (no console window when possible) ----------
echo [stock-system] starting engine on port %PORT% ...
if defined PYW (
  start "stock-engine" /min %PYW% server.py --no-browser --port %PORT%
) else (
  start "stock-engine" /min %PYRUN% server.py --no-browser --port %PORT%
)

rem ---------- 4) wait until it answers (up to ~25s) ----------
powershell -NoProfile -ExecutionPolicy Bypass -Command "for($i=0;$i -lt 50;$i++){try{(New-Object Net.WebClient).DownloadString('%URL%api/health')|Out-Null;exit 0}catch{Start-Sleep -Milliseconds 500}};exit 1" >nul 2>nul
if errorlevel 1 (
  echo [stock-system] engine did not answer in time, opening anyway ...
)

:open_app
set "EDGE=%ProgramFiles(x86)%\Microsoft\Edge\Application\msedge.exe"
set "EDGE2=%ProgramFiles%\Microsoft\Edge\Application\msedge.exe"
set "CHROME=%ProgramFiles%\Google\Chrome\Application\chrome.exe"
set "CHROME2=%ProgramFiles(x86)%\Google\Chrome\Application\chrome.exe"

rem ????????? Edge ????? --start-fullscreen ????
set "PROFILE=%LOCALAPPDATA%\StockSystemApp"
set "APPARGS=--app=%URL% --start-fullscreen --user-data-dir=%PROFILE% --no-first-run --no-default-browser-check"

if exist "%EDGE%"  start "" "%EDGE%"  %APPARGS% & exit /b 0
if exist "%EDGE2%" start "" "%EDGE2%" %APPARGS% & exit /b 0
if exist "%CHROME%" start "" "%CHROME%" %APPARGS% & exit /b 0
if exist "%CHROME2%" start "" "%CHROME2%" %APPARGS% & exit /b 0

start "" "%URL%"
exit /b 0

:no_python
echo.
echo [stock-system] Python 3.10+ not found.
echo   Install from https://www.python.org/downloads/
echo   and tick "Add python.exe to PATH", then run this again.
echo.
pause
exit /b 1
