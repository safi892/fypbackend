@echo off
setlocal EnableExtensions EnableDelayedExpansion

set "ROOT=%~dp0"
cd /d "%ROOT%"

set "PORT=%PORT%"
if not defined PORT set "PORT=8000"

set "MODEL_DIR=%ROOT%codet5_commenst_expla\checkpoint_best"
set "MODEL_PATH=%MODEL_DIR%"
set "TOKENIZER_PATH=%MODEL_DIR%"

set "LOG_DIR=%ROOT%logs"
set "LOG_FILE=%LOG_DIR%\server.log"
set "PID_FILE=%ROOT%.server.pid"

set "VENV_PY=.venv\Scripts\python.exe"
if not exist "%VENV_PY%" (
  echo Virtual environment not found. Run setup.bat first.
  exit /b 1
)

if not exist "%LOG_DIR%" mkdir "%LOG_DIR%"

if not exist "%MODEL_DIR%" (
  echo Model directory not found: %MODEL_DIR%
  echo Run setup.bat to extract or provide the model files.
)

for /f "tokens=5" %%p in ('netstat -ano ^| findstr :%PORT% ^| findstr LISTENING') do (
  echo Port %PORT% is in use by PID %%p. Stopping it...
  taskkill /PID %%p /F >nul 2>&1
)

echo Starting server on port %PORT%...
powershell -NoProfile -Command "$process = Start-Process -FilePath '%VENV_PY%' -ArgumentList @('-m','uvicorn','app.main:app','--host','0.0.0.0','--port','%PORT%') -WorkingDirectory '%ROOT%' -RedirectStandardOutput '%LOG_FILE%' -RedirectStandardError '%LOG_FILE%' -PassThru; $process.Id | Set-Content -Path '%PID_FILE%'"

echo Server started. PID file: %PID_FILE%
echo Logs: %LOG_FILE%
