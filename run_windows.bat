@echo off
rem Leo 3D AI Cartoon Studio - start the desktop app on Windows
cd /d "%~dp0"
if not exist ".venv\Scripts\pythonw.exe" (
  echo Not installed yet. Run: powershell -ExecutionPolicy Bypass -File install_windows.ps1
  pause
  exit /b 1
)
start "" ".venv\Scripts\pythonw.exe" main.py
