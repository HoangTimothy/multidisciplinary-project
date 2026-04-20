@echo off
REM Start DADN API Server on Windows
REM This script installs dependencies and starts the Flask server

echo.
echo ================================
echo DADN API Server - Windows Launcher
echo ================================
echo.

REM Check if Python is installed
python --version >nul 2>&1
if errorlevel 1 (
    echo Error: Python not found. Please install Python from python.org
    pause
    exit /b 1
)

echo Checking dependencies...
pip list | findstr "flask mediapipe opencv-python" >nul

if errorlevel 1 (
    echo Installing dependencies...
    pip install -r requirements_api.txt
    if errorlevel 1 (
        echo Error installing dependencies
        pause
        exit /b 1
    )
)

echo.
echo ================================
echo Starting DADN API Server
echo ================================
echo.
echo Server will run at: http://0.0.0.0:5000
echo Configure ESP32 to send images to your PC IP at port 5000
echo.
echo To find your PC IP, open PowerShell and run:
echo   ipconfig
echo.
echo Press Ctrl+C to stop the server
echo.

python api_server.py

if errorlevel 1 (
    echo.
    echo Error running server. Check error messages above
    pause
    exit /b 1
)
