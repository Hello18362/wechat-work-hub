@echo off
setlocal
cd /d "%~dp0"

echo ==============================================
echo   Refresh WeChat data (SIWX decrypt)
echo ==============================================
echo.
echo Running... (few seconds, keys are cached)
"C:\your-path\AppData\Local\Programs\Python\Python311\python.exe" "C:\your-path\.workbuddy\binaries\siwx\run.py" auto
echo.
echo Done. Decrypted data refreshed.
pause
