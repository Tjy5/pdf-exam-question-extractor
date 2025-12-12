@echo off
setlocal enabledelayedexpansion
chcp 65001 > nul
title ExamPaper AI Web Server

echo ================================================
echo    ExamPaper AI Web Server
echo ================================================
echo.

REM ============================================
REM Step 1: Clean old server process
REM ============================================
echo [Cleanup] Checking port 8000...
echo.

REM Check if port 8000 is in use
for /f "tokens=5" %%a in ('netstat -ano ^| findstr :8000 ^| findstr LISTENING') do (
    set PID=%%a
)

if defined PID (
    echo [WARN] Port 8000 is used by PID %PID%
    echo [Cleanup] Killing old process...
    taskkill /F /PID %PID% >nul 2>&1
    if !errorlevel! equ 0 (
        echo [OK] Old process terminated
    ) else (
        echo [ERROR] Failed to kill process (admin rights may be required)
    )
    echo.
    timeout /t 2 /nobreak >nul
) else (
    echo [OK] Port 8000 is free
    echo.
)

REM Additional cleanup: Kill any Python processes running app.py
echo [Cleanup] Checking other app.py processes...
for /f "tokens=2" %%a in ('tasklist /FI "IMAGENAME eq python.exe" /FO LIST ^| findstr /C:"PID:"') do (
    set PYTHON_PID=%%a
    REM Check if this PID is running app.py
    wmic process where "ProcessId=!PYTHON_PID!" get CommandLine 2>nul | findstr /C:"app.py" >nul
    if !errorlevel! equ 0 (
        echo [Cleanup] Found old app.py PID !PYTHON_PID!, killing...
        taskkill /F /PID !PYTHON_PID! >nul 2>&1
        echo [OK] Cleaned
    )
)
echo [Done] Cleanup finished
echo.

REM ============================================
REM Step 2: Check dependencies
REM ============================================
echo [Check] Verifying FastAPI is installed...
python -c "import fastapi" 2>nul
if %errorlevel% neq 0 (
    echo [INFO] Installing web dependencies...
    echo.
    pip install -r web_requirements.txt
    if %errorlevel% neq 0 (
        echo.
        echo [ERROR] Dependency install failed.
        echo Please check Python/pip.
        pause
        exit /b 1
    )
    echo.
    echo [OK] Dependencies installed
    echo.
) else (
    echo [OK] Dependencies ready
    echo.
)

REM ============================================
REM Step 3: Start server
REM ============================================
echo ================================================
echo [Starting] Launching server...
echo ================================================
echo URL: http://localhost:8000
echo Press Ctrl+C to stop.
echo.

REM Change to web_interface directory
if not exist "web_interface" (
    echo [ERROR] web_interface directory not found.
    echo Run this script from project root.
    pause
    exit /b 1
)

cd web_interface

REM Start the server
echo [Start] Server is starting...
echo.
python app.py

REM If server exits, show message
echo.
echo ================================================
echo [INFO] Server stopped
echo ================================================
echo.

pause
