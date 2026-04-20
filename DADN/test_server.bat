@echo off
REM Quick test of DADN API Server

python --version >nul 2>&1
if errorlevel 1 (
    echo Error: Python not found
    pause
    exit /b 1
)

pip list | findstr "requests" >nul
if errorlevel 1 (
    echo Installing requests...
    pip install requests
)

echo.
echo ================================
echo DADN API Server - Test Script
echo ================================
echo.
echo Make sure the server is running:
echo   python api_server.py
echo.

python test_api.py

pause
