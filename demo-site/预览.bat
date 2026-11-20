@echo off
chcp 936 >nul
cd /d "%~dp0"
title 演示站 - 本地预览

echo ==========================================
echo    沙盘演示站 - 本地预览
echo ==========================================
echo.

REM ---- 找 Python：PATH -> py 启动器 -> 常见安装目录 ----
set "PY="
python -V >nul 2>nul
if not errorlevel 1 set "PY=python"

if not defined PY (
  py -3 -V >nul 2>nul
  if not errorlevel 1 set "PY=py -3"
)

if not defined PY (
  for /f "delims=" %%D in ('dir /b /ad /o-n "%LOCALAPPDATA%\Programs\Python\Python3*" 2^>nul') do (
    if not defined PY if exist "%LOCALAPPDATA%\Programs\Python\%%D\python.exe" set "PY=%LOCALAPPDATA%\Programs\Python\%%D\python.exe"
  )
)

if not defined PY (
  for /f "delims=" %%D in ('dir /b /ad /o-n "C://Program Files//Python3*" 2^>nul') do (
    if not defined PY if exist "C://Program Files//%%D//python.exe" set "PY=C://Program Files\%%D\python.exe"
  )
)

if not defined PY (
  echo [提示] 没找到 Python。
  echo.
  echo   其实这个演示站不用起服务也能看：
  echo   直接双击本文件夹里的 index.html 就行。
  echo.
  echo   想用本地服务的话，先装 Python 3.10+：
  echo   https://www.python.org/downloads/
  echo.
  pause
  exit /b 1
)

echo 正在启动本地服务：http://127.0.0.1:5730
start "" http://127.0.0.1:5730/
%PY% -m http.server 5730

echo.
echo 服务已停止。
pause
