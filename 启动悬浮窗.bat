@echo off
chcp 936 >nul
setlocal enabledelayedexpansion
cd /d "%~dp0"
REM 本文件必须保持 GBK 编码 + CRLF，否则 chcp 936 窗口里中文乱码
set "PYTHONIOENCODING=gbk:replace"

title 桌面悬浮窗 - 启动

echo.
echo  ==========================================
echo    桌面悬浮窗   启动
echo  ==========================================
echo.

if not exist "%~dp0tools\desktop_widget.py" (
  echo  [错误] 找不到 tools\desktop_widget.py
  echo         请把本文件放在项目根目录（和 tools 文件夹同级）。
  echo.
  pause
  exit /b 1
)

REM 必须用「装了 Pillow/requests/yaml/bs4」的那个 Python。
REM 只检查 python -V 会抓错版本，结果窗口刚出现就退出（以前踩过）。
call "%~dp0tools\找Python.bat"
if not defined PY (
  echo  [错误] 没找到装了本项目依赖的 Python。
  echo.
  echo         需要 Python 3.10+，并且装过依赖：
  echo           pip install -e .
  echo         如果装了多个 Python，装依赖的那个要和运行的是同一个。
  echo.
  pause
  exit /b 1
)

echo  使用 Python：%PY%
echo.
%PY% "%~dp0tools\start_widget.py"

if errorlevel 1 (
  echo.
  echo  启动失败。把上面的报错截图发我，我来修。
  pause
  exit /b 1
)

ping -n 4 127.0.0.1 >nul
exit /b 0
