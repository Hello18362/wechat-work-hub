@echo off
chcp 936 >nul
setlocal enabledelayedexpansion
cd /d "%~dp0"
title 刷新微信解密数据

echo.
echo  ==========================================
echo    刷新微信解密数据
echo  ==========================================
echo.

set "PY="
for /f "delims=" %%P in ('where python.exe 2^>nul') do if not defined PY set "PY=%%P"
if not defined PY for /f "delims=" %%P in ('py -3 -c "import sys;print(sys.executable)" 2^>nul') do if not defined PY set "PY=%%P"

if not defined PY (
  echo  [错误] 没有找到 Python，请先安装 Python 3.10+ 并勾选 Add to PATH。
  echo         https://www.python.org/downloads/
  echo.
  pause
  exit /b 1
)

echo  解密目录和工具路径从 .env 读取，换电脑不用改这里的脚本。
echo.
"%PY%" "%~dp0tools\refresh_data.py"
echo.
pause
