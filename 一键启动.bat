@echo off
chcp 936 >nul
setlocal enabledelayedexpansion
cd /d "%~dp0"

REM 让 Python 的输出用 GBK，和 chcp 936 对齐，否则中文在窗口里是乱码
set "PYTHONIOENCODING=gbk:replace"

title 微信群工作助手 - 启动

echo.
echo  ==========================================
echo    微信群工作助手   一键启动
echo  ==========================================
echo.

if not exist "%~dp0tools\launch.py" (
  echo  [错误] 找不到 tools\launch.py
  echo.
  echo         请把这个 .bat 放回项目根目录（和其它 .py 文件在一起）。
  echo.
  pause
  exit /b 1
)

REM ---- 找 Python ----
REM 顺序：PATH 里的 python -> py 启动器 -> 默认安装目录里版本号最高的那个
set "PY="

REM ---- 优先用项目自带的虚拟环境（按 README 建过 .venv 就用它，否则依赖会装到别的 Python 上）----
if not defined PY if exist "%~dp0.venv\Scripts\python.exe" set "PY=%~dp0.venv\Scripts\python.exe"
if not defined PY if exist "%~dp0venv\Scripts\python.exe" set "PY=%~dp0venv\Scripts\python.exe"

python -V >nul 2>nul
if not defined PY if not errorlevel 1 set "PY=python"

if not defined PY (
  py -3 -V >nul 2>nul
if not defined PY if not errorlevel 1 set "PY=py -3"
)

if not defined PY (
  for /f "delims=" %%D in ('dir /b /ad /o-n "%LOCALAPPDATA%\Programs\Python\Python3*" 2^>nul') do (
    if not defined PY if exist "%LOCALAPPDATA%\Programs\Python\%%D\python.exe" set "PY=%LOCALAPPDATA%\Programs\Python\%%D\python.exe"
  )
)

if not defined PY (
  for /f "delims=" %%D in ('dir /b /ad /o-n "C:\Program Files\Python3*" 2^>nul') do (
    if not defined PY if exist "C:\Program Files\%%D\python.exe" set "PY=C:\Program Files\%%D\python.exe"
  )
)

if not defined PY (
  echo  [错误] 没有找到可用的 Python。
  echo.
  echo         请先安装 Python 3.10 或更高版本：
  echo         https://www.python.org/downloads/
  echo.
  echo         安装时一定要勾选 "Add Python to PATH"，装完重新双击本文件。
  echo.
  pause
  exit /b 1
)

echo  使用解释器：%PY%
echo.

%PY% "%~dp0tools\launch.py"

if errorlevel 1 (
  echo.
  echo  启动失败。上面的提示说明了原因。
  echo  如果看不懂，把这段文字截图发出来即可。
  echo.
  pause
  exit /b 1
)

echo.
echo  服务已在后台运行，这个窗口几秒后自动关闭。
echo  要停止服务，双击「停止服务.bat」。
ping -n 5 127.0.0.1 >nul
exit /b 0
