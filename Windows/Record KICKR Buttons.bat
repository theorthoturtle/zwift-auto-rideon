@echo off
cd /d "%~dp0"
if not exist .venv (
  echo Run "Start Auto Ride On.bat" once first to set things up.
  pause
  exit /b 1
)
.venv\Scripts\python sniff_kickr.py
