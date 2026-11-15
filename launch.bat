@echo off
setlocal
cd /d "%~dp0"
if exist "dist\LocalPDFAnonymizer-Reviewed\LocalPDFAnonymizer-Reviewed.exe" (
  start "" "dist\LocalPDFAnonymizer-Reviewed\LocalPDFAnonymizer-Reviewed.exe"
  exit /b
)
if exist ".venv\Scripts\pythonw.exe" (
  start "" ".venv\Scripts\pythonw.exe" "app.py"
  exit /b
)
echo Install Python 3.11+ and dependencies as described in README.md.
pause
