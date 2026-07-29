@echo off
setlocal
cd /d "%~dp0"

if exist "%~dp0runtime\app_env\Scripts\pythonw.exe" (
    start "" "%~dp0runtime\app_env\Scripts\pythonw.exe" "%~dp0main.py"
    exit /b 0
)

where pythonw >nul 2>nul
if errorlevel 1 goto no_python

start "" pythonw "%~dp0main.py"
exit /b 0

:no_python
echo Python was not found. Please install Python or add it to PATH.
pause
exit /b 1
