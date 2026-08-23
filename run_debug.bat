@echo off
setlocal
cd /d "%~dp0"

echo ======================================== >> "%~dp0startup.log"
echo Starting 轻笺 - %date% %time% >> "%~dp0startup.log"
echo ======================================== >> "%~dp0startup.log"

REM Check for virtual environment first
if exist "%~dp0runtime\app_env\Scripts\python.exe" (
    echo [OK] Using virtual environment python >> "%~dp0startup.log"
    "%~dp0runtime\app_env\Scripts\python.exe" "%~dp0main.py" 2>&1 | tee "%~dp0error.log"
    goto :end
)

REM Check system python
where python >nul 2>nul
if errorlevel 1 (
    echo [ERROR] Python not found >> "%~dp0startup.log"
    echo Python was not found. Please install Python or add it to PATH.
    pause
    exit /b 1
)

echo [OK] Using system python >> "%~dp0startup.log"
where python >> "%~dp0startup.log"
python "%~dp0main.py" 2>&1 | tee "%~dp0error.log"

:end
echo. >> "%~dp0startup.log"
echo Process ended with error level: %errorlevel% >> "%~dp0startup.log"
pause
