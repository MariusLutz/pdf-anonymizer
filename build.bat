@echo off
setlocal
cd /d "%~dp0"
set "PYTHONUSERBASE=%~dp0build\python-user"
set "PYINSTALLER_CONFIG_DIR=%~dp0build\pyinstaller-cache"
.venv\Scripts\python.exe -m PyInstaller --noconfirm --clean --windowed --onedir --name LocalPDFAnonymizer-Reviewed --collect-all pymupdf --add-data "tessdata;tessdata" app.py
if errorlevel 1 pause
