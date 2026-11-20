@echo off
chcp 936 >nul
cd /d "%~dp0"
title 打包单文件版

echo ==========================================
echo   把演示站打包成一个 HTML（发微信用）
echo ==========================================
echo.

set "PY="
python -V >nul 2>nul
if not errorlevel 1 set "PY=python"

if not defined PY (
  py -3 -V >nul 2>nul
  if not errorlevel 1 set "PY=py -3"
)

if not defined PY (
  echo [提示] 没找到 Python，无法打包。
  echo.
  echo   打包只是为了生成一个单文件 HTML，
  echo   装个 Python 3.10+ 再双击本文件即可：
  echo   https://www.python.org/downloads/
  echo.
  pause
  exit /b 1
)

%PY% "%~dp0..\tools\build_singlefile.py"
if errorlevel 1 (
  echo.
  echo 打包失败，请把上面的报错发我。
  pause
  exit /b 1
)

echo.
echo 已生成：demo-site\dist\WeChatWorkHub-演示-单文件.html
echo 把这个文件发给对方，点开就能用。
echo.
if exist "%~dp0dist" start "" "%~dp0dist"
pause
