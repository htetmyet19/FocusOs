@echo off
rem FocusOs: start the database and the dashboard, then open the browser.
rem First run also sets up Python packages and creates your private database.
rem Note for editing: inside an "if ( ... )" block, a ")" in an echo ends the
rem block early, so messages in blocks must not contain parentheses.
setlocal
cd /d "%~dp0"

where python >nul 2>nul
if errorlevel 1 (
  echo Python 3.10 or newer is needed: https://www.python.org/downloads/
  echo Tick "Add python.exe to PATH" while installing, then run start.bat again.
  pause
  exit /b 1
)

rem The marker is written only after pip succeeds, so a half-finished install
rem (for example, no internet) is retried next time instead of crashing.
if not exist ".venv\focusos-ready.txt" (
  echo First run: installing the dashboard's Python packages. This takes a minute...
  if not exist ".venv\Scripts\python.exe" python -m venv .venv || goto :fail
  ".venv\Scripts\python.exe" -m pip install --disable-pip-version-check -q -r tracker\dashboard\requirements.txt || goto :fail
  echo ok> ".venv\focusos-ready.txt"
)

if not exist "tracker\build\focus_tracker.exe" (
  echo Note: tracker\build\focus_tracker.exe is missing, so focus sessions can't start.
  echo Use the release zip, or build the tracker as the README explains.
)

set FOCUS_OPEN_BROWSER=1
".venv\Scripts\python.exe" tracker\dashboard\server.py
if errorlevel 1 goto :fail
exit /b 0

:fail
echo.
echo FocusOs could not start. See the message above.
pause
exit /b 1
