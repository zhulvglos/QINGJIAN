@echo off
setlocal
cd /d "%~dp0"

REM Try virtual environment pythonw first (no console window)
if exist "%~dp0runtime\app_env\Scripts\pythonw.exe" (
    start "" /b "%~dp0runtime\app_env\Scripts\pythonw.exe" "%~dp0main.py"
    exit /b 0
)

REM Try system pythonw (no console window)
where pythonw >nul 2>nul
if not errorlevel 1 (
    start "" /b pythonw "%~dp0main.py"
    exit /b 0
)

REM Fallback to python (will show console)
start "" /b python "%~dp0main.py"
exit /b 0
