@echo off
setlocal EnableExtensions EnableDelayedExpansion

set "ROOT=%~dp0"
cd /d "%ROOT%"

set "PYTHON=python"
where py >nul 2>&1 && set "PYTHON=py -3"

%PYTHON% -c "import sys; sys.exit(0 if sys.version_info >= (3, 11) else 1)"
if errorlevel 1 (
  echo Python 3.11+ is required.
  exit /b 1
)

if not exist ".venv\Scripts\python.exe" (
  echo Creating virtual environment...
  %PYTHON% -m venv .venv
)

set "VENV_PY=.venv\Scripts\python.exe"
if not exist "%VENV_PY%" (
  echo Virtual environment python not found.
  exit /b 1
)

"%VENV_PY%" -m pip install --upgrade pip

for /f "delims=" %%d in ('"%VENV_PY%" -c "import pathlib, tomllib; data=tomllib.loads(pathlib.Path('pyproject.toml').read_text()); [print(dep) for dep in data.get('project', {}).get('dependencies', [])]"') do (
  echo Installing %%d
  "%VENV_PY%" -m pip install "%%d"
)

set "MODEL_DIR=%ROOT%codet5_commenst_expla\checkpoint_best"
set "MODEL_ZIP=%ROOT%codet5_commenst_expla.zip"

if not exist "%MODEL_DIR%" (
  if exist "%MODEL_ZIP%" (
    echo Extracting model from codet5_commenst_expla.zip...
    powershell -NoProfile -Command "Expand-Archive -Path '%MODEL_ZIP%' -DestinationPath '%ROOT%' -Force"
  )
)

set "MISSING_FILES="
for %%f in (config.json tokenizer.json model.safetensors) do (
  if not exist "%MODEL_DIR%\%%f" set "MISSING_FILES=!MISSING_FILES! %%f"
)

if "!MISSING_FILES!"=="" (
  echo Model files found in %MODEL_DIR%.
) else (
  if exist "%ROOT%scripts\download_model.py" (
    echo Downloading model via download_model.py...
    "%VENV_PY%" "%ROOT%scripts\download_model.py"
  )
)

if not exist "%ROOT%logs" mkdir "%ROOT%logs"

echo Setup complete.
echo Next: runserver.bat start
