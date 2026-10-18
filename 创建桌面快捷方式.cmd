@echo off
setlocal EnableExtensions
cd /d "%~dp0"
echo.
echo [stock-system] Creating a desktop shortcut with the app icon...
echo.
set "PY="
python -c "import sys" >nul 2>nul
if not errorlevel 1 set "PY=python"
if not defined PY (
  py -3 -c "import sys" >nul 2>nul
  if not errorlevel 1 set "PY=py -3"
)
if not defined PY (
  echo [stock-system] Python 3.10+ not found. Install it first, then run this again.
  echo   https://www.python.org/downloads/
  echo.
  pause
  exit /b 1
)
%PY% tools\make_shortcut.py %*
echo.
echo [stock-system] Done. Look for the "????" icon on your Desktop.
echo.
pause
exit /b 0
