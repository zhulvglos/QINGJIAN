@echo off
setlocal
cd /d "%~dp0"
chcp 65001 >nul

if /I "%~d0"=="C:" (
    echo 请先将轻笺移动到 D、E 等非系统盘，再安装语音组件。
    pause
    exit /b 1
)

set "HTTP_PROXY="
set "HTTPS_PROXY="
set "ALL_PROXY="
set "NO_PROXY=*"
set "PIP_INDEX_URL=https://pypi.tuna.tsinghua.edu.cn/simple"
set "PIP_CACHE_DIR=%~dp0cache\pip"
set "TEMP=%~dp0runtime\temp"
set "TMP=%TEMP%"
if not exist "%PIP_CACHE_DIR%" mkdir "%PIP_CACHE_DIR%"
if not exist "%TEMP%" mkdir "%TEMP%"

echo Installing LightNote voice components...
where python >nul 2>nul
if errorlevel 1 (
    echo Python was not found. Please install Python and add it to PATH.
    pause
    exit /b 1
)

if not exist "%~dp0runtime\app_env\Scripts\python.exe" (
    python -m venv "%~dp0runtime\app_env"
    if errorlevel 1 goto failed
)

"%~dp0runtime\app_env\Scripts\python.exe" -m pip install --index-url "%PIP_INDEX_URL%" --timeout 120 --retries 10 -r "%~dp0requirements-voice.txt"
if errorlevel 1 goto failed

echo.
echo Voice components installed successfully.
pause
exit /b 0

:failed
echo.
echo Installation failed. Check your network or Python proxy settings.
pause
exit /b 1
