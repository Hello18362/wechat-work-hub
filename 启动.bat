@echo off
setlocal
cd /d "%~dp0"

set "PY=C:\your-path\AppData\Local\Programs\Python\Python311\python.exe"
set "PYW=C:\your-path\AppData\Local\Programs\Python\Python311\pythonw.exe"
set "SIWX=C:\your-path\.workbuddy\binaries\siwx\run.py"

echo ==============================================
echo   WeChat Work Hub - one-click launcher
echo ==============================================
echo.

rem ---------- 1. refresh decrypted data (SIWX, few seconds) ----------
echo [1/3] Refreshing WeChat data (SIWX decrypt) ...
if exist "%PY%" if exist "%SIWX%" (
    "%PY%" "%SIWX%" auto >nul 2>&1
)
echo       done.
echo.

rem ---------- 2. start console as background service ----------
echo [2/3] Starting console (http://127.0.0.1:5710) ...
netstat -ano | findstr ":5710" | findstr "LISTENING" >nul
if not errorlevel 1 (
    echo       already running, will reuse it
) else (
    if exist "%PYW%" (
        start "" "%PYW%" "%~dp0tools\serve_hidden.py"
        echo       started in background - no window to keep open
    ) else (
        start "WeChatWorkHub" /min cmd /c "cd /d %~dp0 && "%PY%" main.py --serve"
        echo       started in a minimized window
    )
)

rem ---------- 3. open browser ----------
echo.
echo [3/3] Opening console page ...
ping -n 3 127.0.0.1 >nul
start http://127.0.0.1:5710

echo.
echo ==============================================
echo   Done! Console: http://127.0.0.1:5710
echo.
echo   The service runs in the background.
echo   This window can be closed safely.
echo   To stop it: double-click the stop-service script.
echo ==============================================
echo.
pause
