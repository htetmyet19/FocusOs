@echo off
rem FocusOs: end any running focus session, then stop FocusOs's own database.
rem Closing the FocusOs window already stops the database when no focus
rem session is running; this is for the browser mode and for leftovers.
setlocal
cd /d "%~dp0"

if exist "tracker\build\focus_tracker.exe" "tracker\build\focus_tracker.exe" --stop

if exist ".venv\Scripts\python.exe" (
  ".venv\Scripts\python.exe" tracker\dashboard\portable_db.py stop
) else (
  python tracker\dashboard\portable_db.py stop
)
timeout /t 2 >nul
