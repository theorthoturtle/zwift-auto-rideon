@echo off
REM Double-click to run. First run sets up a private Python environment.
cd /d "%~dp0"
where py >nul 2>nul && (set PY=py -3) || (set PY=python)
if not exist .venv (
  echo First run: setting up ^(one time^)...
  %PY% -m venv .venv || goto :nopython
  .venv\Scripts\python -m pip install -q zeroconf || goto :fail
)
if "%~1"=="--setup-only" exit /b 0
.venv\Scripts\python auto_rideon.py %*
pause
exit /b

:nopython
echo Python 3 was not found. Install it from https://www.python.org/downloads/windows/
echo (tick "Add python.exe to PATH" during install), then run this again.
pause
exit /b 1

:fail
echo Setup failed.
pause
exit /b 1
