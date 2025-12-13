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
REM Step 3: Configure model optimization
REM ============================================
echo ================================================
echo [Config] Model Optimization Settings
echo ================================================
echo.

REM GPU Acceleration
set "EXAMPAPER_USE_GPU=1"
echo [Config] GPU Acceleration: ENABLED (NVIDIA RTX 3060)

REM GPU Memory Limit (80%% to prevent OOM)
set "FLAGS_fraction_of_gpu_memory_to_use=0.8"
echo [Config] GPU Memory Limit: 80%% (4.8GB / 6GB)

REM PaddlePaddle GPU Performance Optimization
set "FLAGS_allocator_strategy=auto_growth"
set "FLAGS_cudnn_deterministic=0"
set "FLAGS_cudnn_batchnorm_spatial_persistent=1"
set "FLAGS_conv_workspace_size_limit=4096"
echo [Config] GPU Memory Strategy: Auto-growth
echo [Config] CUDNN Optimization: ENABLED

echo.

REM In-process execution (avoid reloading models)
set "EXAMPAPER_STEP1_INPROC=1"
set "EXAMPAPER_STEP2_INPROC=1"
echo [Config] Step 1 (Question Extraction) In-process: ENABLED
echo [Config] Step 2 (Data Analysis) In-process: ENABLED

REM Model warmup (preload on startup)
set "EXAMPAPER_PPSTRUCTURE_WARMUP=1"
echo [Config] Model warmup: ENABLED

REM Async warmup (server starts immediately, model loads in background)
set "EXAMPAPER_PPSTRUCTURE_WARMUP_ASYNC=1"
echo [Config] Warmup mode: ASYNC (server ready immediately)

REM Fallback to subprocess if in-proc fails
set "EXAMPAPER_STEP1_FALLBACK_SUBPROCESS=1"
set "EXAMPAPER_STEP2_FALLBACK_SUBPROCESS=1"
echo [Config] Subprocess fallback: ENABLED

REM Table recognition (keep enabled for data analysis)
set "EXAMPAPER_LIGHT_TABLE=0"
echo [Config] Table recognition: ENABLED

echo.

REM ============================================
REM Parallel Extraction Settings
REM ============================================
REM Enable parallel page processing for question extraction
REM This uses ThreadPoolExecutor with GPU serialization
set "EXAMPAPER_PARALLEL_EXTRACTION=1"
set "EXAMPAPER_MAX_WORKERS=4"
echo [Config] Parallel extraction: ENABLED
echo [Config] Max workers: 4 (GPU serialized, CPU parallel)

echo.
echo [INFO] Model is preloading in background (async mode)
echo [INFO] Server will be accessible immediately at http://localhost:8000
echo [INFO] Model warmup: ~15-30 seconds (background, non-blocking)
echo [INFO] First request may wait for model if submitted during warmup
echo [INFO] Expected performance improvement:
echo [INFO]   - Question extraction (Step 1): ~10-20x faster
echo [INFO]   - Data analysis (Step 2): ~50-100x faster (8min to 10s)
echo [INFO]   - Overall pipeline: ~5-10x faster
echo.

REM ============================================
REM Step 4: Start server
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
