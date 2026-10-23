@echo off
rem Start WeChat Work Hub console as a windowless background service.
rem Safe to run many times: exits quietly if already running.
setlocal
cd /d "%~dp0"

set "PY=C:\your-path\AppData\Local\Programs\Python\Python311\python.exe"
set "PYW=C:\your-path\AppData\Local\Programs\Python\Python311\pythonw.exe"
set "SIWX=C:\your-path\.workbuddy\binaries\siwx\run.py"

rem --- 1. refresh decrypted WeChat data (silent, a few seconds) ---
if exist "%PY%" if exist "%SIWX%" (
    "%PY%" "%SIWX%" auto >nul 2>&1
)

rem --- 2. already listening? then do nothing ---
netstat -ano | findstr ":5710" | findstr "LISTENING" >nul
if not errorlevel 1 exit /b 0

rem --- 3. launch hidden ---
if not exist "%PYW%" exit /b 1
start "" "%PYW%" "%~dp0tools\serve_hidden.py"
exit /b 0
