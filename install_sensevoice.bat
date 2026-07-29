@echo off
setlocal
chcp 65001 >nul
cd /d "%~dp0"

if /I "%~d0"=="C:" (
  echo 请先将轻笺移动到 D、E 等非系统盘，再安装 SenseVoice。
  pause
  exit /b 1
)

where python >nul 2>nul
if errorlevel 1 (
  echo 未找到 Python，请先安装并加入 PATH。
  pause
  exit /b 1
)

set "SV_ROOT=%~d0\LightNoteSenseVoice"
powershell -NoProfile -Command "$target=(Resolve-Path '%~dp0').Path.TrimEnd('\'); if (-not (Test-Path '%SV_ROOT%')) { New-Item -ItemType Junction -Path '%SV_ROOT%' -Target $target | Out-Null }"
if errorlevel 1 goto :failed

set "TEMP=%SV_ROOT%\runtime\temp"
set "TMP=%TEMP%"
set "PIP_CACHE_DIR=%SV_ROOT%\cache\pip"
set "MODELSCOPE_CACHE=%SV_ROOT%\cache\modelscope"
set "MODELSCOPE_HOME=%MODELSCOPE_CACHE%"
set "HF_HOME=%SV_ROOT%\cache\huggingface"
set "TORCH_HOME=%SV_ROOT%\cache\torch"
if not exist "%TEMP%" mkdir "%TEMP%"
if not exist "%PIP_CACHE_DIR%" mkdir "%PIP_CACHE_DIR%"

if not exist "%SV_ROOT%\runtime\sensevoice_env\Scripts\python.exe" (
  python -m venv "%SV_ROOT%\runtime\sensevoice_env"
  if errorlevel 1 goto :failed
)
"%SV_ROOT%\runtime\sensevoice_env\Scripts\python.exe" -m pip install -r "%SV_ROOT%\requirements-sensevoice.txt" -i https://pypi.tuna.tsinghua.edu.cn/simple --trusted-host pypi.tuna.tsinghua.edu.cn
if errorlevel 1 goto :failed
echo SenseVoice 独立环境安装完成。模型文件请保存在 %SV_ROOT%\models。
pause
exit /b 0

:failed
echo 安装失败。请先关闭代理，再重新运行本脚本。
pause
exit /b 1
