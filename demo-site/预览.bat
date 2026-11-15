@echo off
chcp 936 >nul
cd /d "%~dp0"
title 演示站 - 本地预览

echo ==========================================
echo    沙盘演示站 - 本地预览
echo ==========================================
echo.

set "PY=C:\your-path\AppData\Local\Programs\Python\Python311\python.exe"
if not exist "%PY%" (
    echo [错误] 找不到 Python：%PY%
    pause
    exit /b 1
)

echo 正在启动本地服务：http://127.0.0.1:5730
start "" http://127.0.0.1:5730/
"%PY%" -m http.server 5730

echo.
echo 服务已停止。
pause
