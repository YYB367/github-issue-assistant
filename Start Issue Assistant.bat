@echo off
setlocal
chcp 65001 >nul
cd /d "%~dp0"
if not exist ".venv\Scripts\python.exe" (
  echo Python environment is missing. Follow README installation steps first.
  pause
  exit /b 1
)
".venv\Scripts\python.exe" -X utf8 -m scripts.launcher
if errorlevel 1 pause
