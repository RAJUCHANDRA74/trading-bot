@echo off
title SARTrader Platform
cd /d "%~dp0"

echo.
echo  ================================================
echo     SARTrader Platform v1.0
echo     Mode: PAPER TRADING
echo  ================================================
echo.

REM Check Python
python --version >nul 2>&1
if errorlevel 1 (
    echo ERROR: Python not found. Please install Python 3.9+
    pause
    exit /b 1
)

REM Install dependencies if needed
echo [1/2] Checking dependencies...
pip install websockets aiohttp --quiet 2>nul

REM Start the platform
echo [2/2] Starting platform...
echo.
echo  Dashboard: http://localhost:8765
echo  Press Ctrl+C to stop
echo.

python -m sartrader.engine

pause
