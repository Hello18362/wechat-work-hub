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
REM 顺序：项目自带 .venv -> PATH 里的 python -> py 启动器 -> 默认安装目录里版本号最高的那个
REM 一律解析成完整路径，后面统一用 "%PY%" 调用，避免 "C:\Program Files\..." 被空格截断。
set "PY="

if exist "%~dp0.venv\Scripts\python.exe" set "PY=%~dp0.venv\Scripts\python.exe"
if not defined PY if exist "%~dp0venv\Scripts\python.exe" set "PY=%~dp0venv\Scripts\python.exe"

if not defined PY (
  python -V >nul 2>nul
  if not errorlevel 1 for /f "delims=" %%P in ('python -c "import sys;print(sys.executable)" 2^>nul') do set "PY=%%P"
)

if not defined PY (
  py -3 -V >nul 2>nul
  if not errorlevel 1 for /f "delims=" %%P in ('py -3 -c "import sys;print(sys.executable)" 2^>nul') do set "PY=%%P"
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

REM ---- 首次运行：自动建虚拟环境，之后所有依赖都装进它 ----
REM 这一步是给「只想双击一次」的人准备的：不建 .venv 的话，依赖会装进系统
REM Python，之后换成别的 Python 跑就又是 ModuleNotFoundError。
if not exist "%~dp0.venv\Scripts\python.exe" (
  echo  首次运行：正在创建虚拟环境 .venv（约十秒）...
  "%PY%" -m venv "%~dp0.venv" >nul 2>nul
  if exist "%~dp0.venv\Scripts\python.exe" (
    echo  虚拟环境已创建：.venv
  ) else (
    echo  [提示] 虚拟环境没建起来，这次直接用上面那个 Python 运行。
  )
)
if exist "%~dp0.venv\Scripts\python.exe" set "PY=%~dp0.venv\Scripts\python.exe"

echo  使用解释器：%PY%
echo.

"%PY%" "%~dp0tools\launch.py"

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
