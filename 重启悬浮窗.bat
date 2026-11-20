@echo off
chcp 936 >nul
setlocal enabledelayedexpansion
cd /d "%~dp0"
set "PYTHONIOENCODING=gbk:replace"
title 重启悬浮窗

echo.
echo  ==========================================
echo    重启悬浮窗（先关旧的，再拉新的）
echo  ==========================================
echo.

if not exist "%~dp0tools\start_widget.py" (
  echo  [错误] 找不到 tools\start_widget.py，请把本文件放在项目根目录。
  pause
  exit /b 1
)

call "%~dp0tools\找Python.bat"
if not defined PY (
  echo  [错误] 没找到装了本项目依赖的 Python（需要 Pillow / requests / yaml / bs4）。
  echo         先执行：pip install -e .
  pause
  exit /b 1
)

echo  使用 Python：%PY%
echo.
%PY% "%~dp0tools\start_widget.py" --restart

echo.
echo  （5 秒后自动关闭）
timeout /t 5 >nul
