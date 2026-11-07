@echo off
title Claw - Your Jarvis
cd /d "%~dp0"

where python >nul 2>nul
if errorlevel 1 (
  echo.
  echo  Python was not found on this computer.
  echo  Install it from https://www.python.org/downloads/
  echo  IMPORTANT: tick the box "Add python.exe to PATH" during install.
  echo.
  pause
  exit /b 1
)

if not exist ".venv" (
  echo Creating virtual environment...
  python -m venv .venv
)

call .venv\Scripts\activate.bat

if not exist ".venv\.deps_installed" (
  echo Installing Jarvis components, one moment...
  pip install -r requirements.txt
  if errorlevel 1 (
    echo.
    echo  Installation failed. Check your internet connection and double-click me again.
    echo.
    pause
    exit /b 1
  )
  echo done> .venv\.deps_installed
)

echo.
echo   ==========================================
echo    Your Jarvis is starting...
echo    It will open in your browser automatically.
echo    Close this window to stop Jarvis.
echo   ==========================================
echo.

start /b cmd /c "timeout /t 4 >nul & start http://localhost:8000"
python run.py
pause
