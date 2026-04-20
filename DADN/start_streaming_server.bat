@echo off
REM ESP32-CAM Streaming + DADN Detection Server Launcher
REM This script will start the server with your ESP32-CAM stream

setlocal enabledelayedexpansion

echo.
echo ================================================================
echo   ESP32-CAM Streaming + Object Detection Server Launcher
echo ================================================================
echo.

REM Check if Python is installed
python --version >nul 2>&1
if errorlevel 1 (
    echo Error: Python is not installed or not in PATH
    echo Please install Python 3.8+ from https://www.python.org
    pause
    exit /b 1
)

REM Get PC IP
for /f "tokens=2 delims=:" %%a in ('ipconfig ^| findstr "IPv4 Address"') do (
    for /f "tokens=1,2,3,4" %%i in ("%%a") do (
        set "PC_IP=%%i.%%j.%%k.%%l"
    )
)

echo.
echo Step 1: Enter ESP32-CAM Stream URL
echo =================================
echo This is typically: http://[ESP32_IP]:8081/stream
echo.
echo Where [ESP32_IP] can be found in:
echo - Serial Monitor of Arduino IDE
echo - Serial output showing "Local IP: ..."
echo.
echo Default example: http://192.168.1.50:8081/stream
echo.

set /p ESP32_URL="Enter ESP32-CAM stream URL (press Enter for default): "

if "%ESP32_URL%"=="" (
    set "ESP32_URL=http://192.168.1.50:8081/stream"
    echo Using default URL: %ESP32_URL%
)

echo.
echo Step 2: Starting server...
echo =========================
echo.
echo Your PC IP: %PC_IP%
echo Server port: 5000
echo.
echo Access the web interface at:
echo   http://localhost:5000
echo   http://%PC_IP%:5000
echo.
echo Press Ctrl+C to stop the server
echo.
echo ================================================================
echo.

REM Run the server
python run_stream_server.py --esp32-url "%ESP32_URL%"

if errorlevel 1 (
    echo.
    echo Error occurred. Press any key to exit...
    pause
    exit /b 1
)
