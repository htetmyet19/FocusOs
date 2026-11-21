@echo off
rem FocusOs: end any running focus session, then stop FocusOs's own database.
rem (Close the dashboard window with Ctrl+C first, or just close it.)
setlocal
cd /d "%~dp0"

if exist "tracker\build\focus_tracker.exe" "tracker\build\focus_tracker.exe" --stop

if exist ".venv\Scripts\python.exe" (
  ".venv\Scripts\python.exe" tracker\dashboard\portable_db.py stop
) else (
  python tracker\dashboard\portable_db.py stop
)
timeout /t 2 >nul
