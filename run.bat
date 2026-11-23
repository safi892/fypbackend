@echo off
setlocal EnableExtensions EnableDelayedExpansion
chcp 65001 >nul 2>&1
cd /d "%~dp0"
set "ROOT=%~dp0"
title FYP Backend Launcher - Windows

:: Parse command arguments: start (default), stop, status
set "ACTION=start"
if /i "%~1"=="stop" set "ACTION=stop"
if /i "%~1"=="--stop" set "ACTION=stop"
if /i "%~1"=="status" set "ACTION=status"
if /i "%~1"=="--status" set "ACTION=status"
if /i "%~1"=="help" goto :usage
if /i "%~1"=="--help" goto :usage
if /i "%~1"=="-h" goto :usage

:: Default ports
set "API_PORT=8000"
set "MODEL_PORT=8081"

:: Load settings from .env if present
if exist ".env" (
  for /f "usebackq tokens=1* delims==" %%A in (".env") do (
    set "k=%%A"
    set "v=%%B"
    if not "!k:~0,1!"=="#" if not "!k!"=="" (
      if /i "!k!"=="PORT" set "API_PORT=!v!"
      if /i "!k!"=="LLAMA_PORT" set "MODEL_PORT=!v!"
    )
  )
)

if "%ACTION%"=="stop" goto :do_stop
if "%ACTION%"=="status" goto :do_status
if "%ACTION%"=="start" goto :do_start

:usage
echo.
echo ============================================================
echo  FYP Backend - Windows Launcher
echo ============================================================
echo Usage: run.bat [start ^| stop ^| status]
echo.
echo   run.bat         Start model server and FastAPI backend
echo   run.bat stop    Stop running backend and model servers
echo   run.bat status  Check server status and health
echo.
exit /b 0

:do_stop
echo.
echo ============================================================
echo  Stopping FYP Backend Services
echo ============================================================
for %%P in (%MODEL_PORT% %API_PORT%) do (
  powershell -NoProfile -Command "Get-NetTCPConnection -LocalPort %%P -State Listen -ErrorAction SilentlyContinue | ForEach-Object { Stop-Process -Id $_.OwningProcess -Force -ErrorAction SilentlyContinue }" >nul 2>&1
)
if exist ".server.pid" del ".server.pid" >nul 2>&1
echo Stopped services listening on port %MODEL_PORT% and %API_PORT%.
exit /b 0

:do_status
echo.
echo ============================================================
echo  FYP Backend Status
echo ============================================================
echo [Model Server :%MODEL_PORT%]
where curl.exe >nul 2>&1
if not errorlevel 1 (
  curl.exe -s --max-time 2 "http://127.0.0.1:%MODEL_PORT%/health" 2>nul
  if errorlevel 1 (
    echo Model server is not running or not answering on port %MODEL_PORT%.
  ) else (
    echo.
  )
) else (
  echo curl.exe not found to check model status.
)

echo.
echo [API Server :%API_PORT%]
if not errorlevel 1 (
  curl.exe -s --max-time 2 "http://127.0.0.1:%API_PORT%/health" 2>nul
  if errorlevel 1 (
    echo API server is not running or not answering on port %API_PORT%.
  ) else (
    echo.
  )
) else (
  echo curl.exe not found to check API status.
)
exit /b 0

:do_start
echo.
echo ============================================================
echo  Starting FYP Backend on Windows
echo ============================================================

:: 1. Check Python virtual environment
set "PYTHON_EXE="
if exist ".venv\Scripts\python.exe" (
  set "PYTHON_EXE=%ROOT%.venv\Scripts\python.exe"
) else (
  for /f "delims=" %%P in ('where python.exe 2^>nul') do if not defined PYTHON_EXE set "PYTHON_EXE=%%P"
)

if not defined PYTHON_EXE (
  echo [ERROR] Python not found in .venv\Scripts\python.exe or PATH.
  echo Please run setup.bat first to set up Python and dependencies.
  pause
  exit /b 1
)

:: 2. Check for GGUF model and llama-server
set "LLAMA_EXE="
for /f "delims=" %%W in ('where llama-server.exe 2^>nul') do if not defined LLAMA_EXE set "LLAMA_EXE=%%W"
if not defined LLAMA_EXE if exist "%ROOT%tools\llama.cpp\llama-server.exe" set "LLAMA_EXE=%ROOT%tools\llama.cpp\llama-server.exe"
if not defined LLAMA_EXE if exist "%ROOT%tools\llama-server.exe" set "LLAMA_EXE=%ROOT%tools\llama-server.exe"

set "GGUF="
if exist "%ROOT%models\gguf\cpp-review-v3-q4_k_m.gguf" set "GGUF=%ROOT%models\gguf\cpp-review-v3-q4_k_m.gguf"
if not defined GGUF if exist "%ROOT%models\gguf\cpp-review-q4_k_m.gguf" set "GGUF=%ROOT%models\gguf\cpp-review-q4_k_m.gguf"
if not defined GGUF if exist "%ROOT%models\gguf\qwen-cpp-review-v3-q4_k_m.gguf" set "GGUF=%ROOT%models\gguf\qwen-cpp-review-v3-q4_k_m.gguf"
if not defined GGUF if exist "%ROOT%models\gguf\qwen-cpp-review-q4_k_m.gguf" set "GGUF=%ROOT%models\gguf\qwen-cpp-review-q4_k_m.gguf"

set "THREADS=8"
for /f "usebackq delims=" %%C in (`powershell -NoProfile -Command "(Get-CimInstance Win32_ComputerSystem).NumberOfLogicalProcessors" 2^>nul`) do if not "%%C"=="" set "THREADS=%%C"

:: Check if Model Server is already running
set "MODEL_RUNNING=0"
where curl.exe >nul 2>&1
if not errorlevel 1 (
  curl.exe -s --max-time 2 "http://127.0.0.1:%MODEL_PORT%/health" 2>nul | findstr /c:"status" >nul 2>&1
  if not errorlevel 1 set "MODEL_RUNNING=1"
)

if "%MODEL_RUNNING%"=="1" (
  echo [1/2] Model server is already active on port %MODEL_PORT%.
) else (
  if defined LLAMA_EXE if defined GGUF (
    echo [1/2] Launching llama-server on port %MODEL_PORT%...
    start "llama-server :%MODEL_PORT%" "!LLAMA_EXE!" -m "!GGUF!" --port %MODEL_PORT% -c 4096 -t !THREADS!
    timeout /t 3 /nobreak >nul
  ) else (
    echo [1/2] Note: llama-server.exe or GGUF weights not found.
    echo       (Run setup.bat if you need local GGUF model acceleration)
  )
)

:: 3. Check if API is already running
set "API_RUNNING=0"
where curl.exe >nul 2>&1
if not errorlevel 1 (
  curl.exe -s --max-time 2 "http://127.0.0.1:%API_PORT%/health" 2>nul | findstr /c:"status" >nul 2>&1
  if not errorlevel 1 set "API_RUNNING=1"
)

if "%API_RUNNING%"=="1" (
  echo [2/2] FastAPI backend is already running on port %API_PORT%.
) else (
  echo [2/2] Launching FastAPI backend on port %API_PORT%...
  if not exist "logs" mkdir "logs"
  start "fyp-api :%API_PORT%" "!PYTHON_EXE!" -m uvicorn app.main:app --host 0.0.0.0 --port %API_PORT%
  timeout /t 3 /nobreak >nul
)

echo.
echo ============================================================
echo  FYP Backend Services Ready
echo ============================================================
echo   API URL      : http://localhost:%API_PORT%/
echo   Interactive  : http://localhost:%API_PORT%/docs
echo   Health Check : http://localhost:%API_PORT%/health
echo   Stop Servers : run.bat stop
echo ============================================================
echo.
exit /b 0
