@echo off
REM =====================================================================
REM  找 Python：只认「装了本项目依赖」的那个
REM
REM  为什么需要它：机器上常有多个 Python（比如 WorkBuddy 自带的 3.13、
REM  商店版、conda）。以前 bat 只看 `python -V` 通不通，结果抓到没装
REM  Pillow 的那个，悬浮窗刚建好窗口就 ImportError 退出 —— 表现就是
REM  "双击完 bat，卡片过一会儿自己没了"。
REM
REM  用法（不要直接双击）：  call "%~dp0tools\找Python.bat"
REM  成功：环境变量 PY 有值（可能是带参数的，如 py -3）
REM  失败：PY 为空，调用方自己提示
REM =====================================================================
set "PY="

REM ---- 优先用项目自带的虚拟环境（按 README 建过 .venv 就用它，否则依赖会装到别的 Python 上）----
if not defined PY if exist "%~dp0..\.venv\Scripts\python.exe" set "PY=%~dp0..\.venv\Scripts\python.exe"
if not defined PY if exist "%~dp0..\venv\Scripts\python.exe" set "PY=%~dp0..\venv\Scripts\python.exe"
if defined PY "%PY%" -c "import PIL,requests,yaml,bs4" >nul 2>nul || set "PY="

call :trycmd python
if not defined PY call :trycmd python3
if not defined PY call :trycmd py

if not defined PY (
  for /f "delims=" %%D in ('dir /b /ad /o-n "%LOCALAPPDATA%\Programs\Python\Python3*" 2^>nul') do (
    call :tryfile "%LOCALAPPDATA%\Programs\Python\%%D\python.exe"
  )
)
if not defined PY (
  for /f "delims=" %%D in ('dir /b /ad /o-n "%ProgramFiles%\Python3*" 2^>nul') do (
    call :tryfile "%ProgramFiles%\%%D\python.exe"
  )
)
if not defined PY (
  for /f "delims=" %%D in ('dir /b /ad /o-n "C:/Python3*" 2^>nul') do (
    call :tryfile "C:/%%D/python.exe"
  )
)

if defined PY exit /b 0
exit /b 1

REM ---- 候选：PATH 上的命令名 ----
:trycmd
if defined PY goto :eof
where %~1 >nul 2>nul || goto :eof
%~1 -c "import PIL,requests,yaml,bs4" >nul 2>nul || goto :eof
set "PY=%~1"
goto :eof

REM ---- 候选：完整路径 ----
:tryfile
if defined PY goto :eof
if not exist "%~1" goto :eof
"%~1" -c "import PIL,requests,yaml,bs4" >nul 2>nul || goto :eof
set "PY=%~1"
goto :eof
