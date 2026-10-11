@echo off
setlocal EnableExtensions EnableDelayedExpansion
chcp 65001 >nul 2>&1
cd /d "%~dp0"
set "ROOT=%~dp0"
title FYP Backend - Windows

set "MODEL_PORT=8081"
set "API_PORT=8080"
set "ACTION=setup"
set "WITH_CODET5=0"
set "SKIP_TESTS=0"
set "FORCE_TESTS=0"
set "TESTS_FAILED=0"
set "LLAMA_OK=0"
set "MODEL_OK=0"
set "ROMAN_OK=0"
set "PY_CHANGED=0"
set "MODEL_FETCHED=0"
set "ROMAN_FETCHED=0"
set "NEW_COUNT=0"
set "TESTS_RAN=0"
set "STAMP=tools\.setup-stamp"
if not defined LLAMA_VULKAN set "LLAMA_VULKAN=0"

:parse_args
if "%~1"=="" goto :args_done
set "ARG_OK=0"
if /i "%~1"=="setup" (set "ACTION=setup" & set "ARG_OK=1")
if /i "%~1"=="start" (set "ACTION=start" & set "ARG_OK=1")
if /i "%~1"=="stop" (set "ACTION=stop" & set "ARG_OK=1")
if /i "%~1"=="status" (set "ACTION=status" & set "ARG_OK=1")
if /i "%~1"=="--with-codet5" (set "WITH_CODET5=1" & set "ARG_OK=1")
if /i "%~1"=="--vulkan" (set "LLAMA_VULKAN=1" & set "ARG_OK=1")
if /i "%~1"=="--skip-tests" (set "SKIP_TESTS=1" & set "ARG_OK=1")
if /i "%~1"=="--test" (set "FORCE_TESTS=1" & set "ARG_OK=1")
if /i "%~1"=="--model-url" (
  if "%~2"=="" (
    echo --model-url needs a value.
    goto :usage
  )
  set "MODEL_URL=%~2"
  set "ARG_OK=1"
  shift
)
if /i "%~1"=="--roman-url" (
  if "%~2"=="" (
    echo --roman-url needs a value.
    goto :usage
  )
  set "ROMAN_URL=%~2"
  set "ARG_OK=1"
  shift
)
if /i "%~1"=="--help" goto :usage
if /i "%~1"=="-h" goto :usage
if "!ARG_OK!"=="0" (
  echo Unknown option: %~1
  goto :usage
)
shift
goto :parse_args
:args_done

if /i "%ACTION%"=="start" goto :cmd_start
if /i "%ACTION%"=="stop" goto :cmd_stop
if /i "%ACTION%"=="status" goto :cmd_status


call :banner "[05/100] Preflight checks"
where curl.exe >nul 2>&1
if errorlevel 1 (
  echo curl.exe not found. It ships with Windows 10 1803 or newer.
  goto :fail
)
where powershell >nul 2>&1
if errorlevel 1 (
  echo PowerShell not found. It is required to unpack downloads.
  goto :fail
)
if not exist "pyproject.toml" (
  echo pyproject.toml not found - run this script from the project root.
  goto :fail
)
if not exist "logs" mkdir "logs"
if not exist "tools" mkdir "tools"
if not exist "models" mkdir "models"
if not exist "models\gguf" mkdir "models\gguf"
if not exist "models\roman-model" mkdir "models\roman-model"
echo project : %ROOT%
echo machine : %PROCESSOR_ARCHITECTURE%


call :banner "[15/100] uv and Python 3.11"
set "PATH=%USERPROFILE%\.local\bin;%USERPROFILE%\.cargo\bin;%PATH%"
where uv >nul 2>&1
if errorlevel 1 goto :install_uv
goto :uv_ready

:install_uv
echo uv not found - installing it.
powershell -NoProfile -ExecutionPolicy Bypass -Command "irm https://astral.sh/uv/install.ps1 | iex"
set "PATH=%USERPROFILE%\.local\bin;%USERPROFILE%\.cargo\bin;%PATH%"
where uv >nul 2>&1
if errorlevel 1 (
  echo official installer did not put uv on PATH - trying pip.
  python -m pip install --upgrade uv
)
where uv >nul 2>&1
if errorlevel 1 (
  echo Could not install uv. See https://docs.astral.sh/uv/getting-started/installation/
  goto :fail
)

:uv_ready
uv --version
uv python find 3.11 >nul 2>&1
if not errorlevel 1 (
  echo python 3.11 already available - skipping install
  goto :python_ready
)
echo installing python 3.11...
uv python install 3.11
if errorlevel 1 (
  echo uv could not install Python 3.11.
  goto :fail
)
set "PY_CHANGED=1"
set /a NEW_COUNT+=1

:python_ready


call :banner "[30/100] Python dependencies"
set "UV_LOG=%TEMP%\fyp_uvsync.log"
if exist "%UV_LOG%" del "%UV_LOG%"
if "%WITH_CODET5%"=="1" (
  echo installing the optional codet5 extra as well (about 2 GB)...
  uv sync --extra codet5 >"%UV_LOG%" 2>&1
) else (
  uv sync >"%UV_LOG%" 2>&1
)
set "SYNC_RC=0"
if errorlevel 1 set "SYNC_RC=1"
type "%UV_LOG%"
if "%SYNC_RC%"=="1" goto :fail
findstr /i /c:"Installed" /c:"Uninstalled" /c:"Removed" /c:"Updated" "%UV_LOG%" >nul 2>&1
if errorlevel 1 (
  echo every python package was already present - nothing installed
) else (
  echo packages changed this run
  set "PY_CHANGED=1"
  set /a NEW_COUNT+=1
)
if not exist ".venv\Scripts\python.exe" (
  echo .venv\Scripts\python.exe is missing after uv sync.
  goto :fail
)
".venv\Scripts\python.exe" --version


call :banner "[45/100] llama.cpp (llama-server)"
call :find_llama
if defined LLAMA_EXE (
  echo already present - skipping download
  goto :llama_ready
)
echo Downloading the Windows build from GitHub releases...
set "LLAMA_TAG="
for /f "usebackq delims=" %%T in (`powershell -NoProfile -Command "$r = Invoke-RestMethod 'https://api.github.com/repos/ggml-org/llama.cpp/releases?per_page=30'; @($r | Where-Object { $_.tag_name -match '^b[0-9]+$' } | Select-Object -First 1 -ExpandProperty tag_name)"`) do set "LLAMA_TAG=%%T"
if not defined LLAMA_TAG (
  echo Could not read the llama.cpp release list from the GitHub API.
  goto :fail
)
set "ARCH=x64"
if /i "%PROCESSOR_ARCHITECTURE%"=="ARM64" set "ARCH=arm64"
if /i "%PROCESSOR_ARCHITEW6432%"=="ARM64" set "ARCH=arm64"
set "FLAVOR=cpu"
if "%LLAMA_VULKAN%"=="1" set "FLAVOR=vulkan"
if /i not "%ARCH%"=="x64" set "FLAVOR=cpu"
set "ASSET=llama-!LLAMA_TAG!-bin-win-!FLAVOR!-!ARCH!.zip"
set "LLAMA_URL=https://github.com/ggml-org/llama.cpp/releases/download/!LLAMA_TAG!/!ASSET!"
echo build : !LLAMA_TAG!  flavor: !FLAVOR!  arch: !ARCH!
call :download "!LLAMA_URL!" "tools\!ASSET!"
if errorlevel 1 goto :fail
powershell -NoProfile -Command "Expand-Archive -Force -Path '%ROOT%tools\!ASSET!' -DestinationPath '%ROOT%tools\llama.cpp'"
if errorlevel 1 (
  echo Could not unpack !ASSET!
  goto :fail
)
del "tools\!ASSET!"
call :find_llama
if not defined LLAMA_EXE (
  echo llama-server.exe was not found inside the downloaded archive.
  goto :fail
)
call :add_llama_to_path
set /a NEW_COUNT+=1

:llama_ready
set "LLAMA_OK=1"
for %%F in ("!LLAMA_EXE!") do set "LLAMA_DIR=%%~dpF"
echo exe   : !LLAMA_EXE!
echo check : running --version once (a missing runtime DLL shows up here)
"!LLAMA_EXE!" --version 2>&1
echo.


call :banner "[65/100] Qwen GGUF weights"
call :find_gguf
if not defined GGUF if defined MODEL_URL call :fetch_gguf
if not defined GGUF call :find_gguf
if defined GGUF (
  set "MODEL_OK=1"
  if "%MODEL_FETCHED%"=="1" (
    echo downloaded : !GGUF!
    set /a NEW_COUNT+=1
  ) else (
    echo already present - skipping download: !GGUF!
  )
) else (
  echo WARNING: no .gguf file under models\gguf
  echo          The API still runs, but the qwen_gguf backend cannot start.
  echo          Put the weights at models\gguf\qwen-cpp-review-v3-q4_k_m.gguf
  echo          or re-run with:  setup.bat --model-url ^<direct download link^>
)


call :banner "[80/100] Roman Urdu T5 model"
call :find_roman
if not defined ROMAN_OK if defined ROMAN_URL call :fetch_roman
call :find_roman
if defined ROMAN_OK (
  if "%ROMAN_FETCHED%"=="1" (
    echo downloaded : models\roman-model\t5-stage2-c
    set /a NEW_COUNT+=1
  ) else (
    echo already present - skipping download: models\roman-model\t5-stage2-c
  )
) else (
  echo WARNING: models\roman-model\t5-stage2-c is incomplete.
  echo          Roman Urdu requests fall back to the rule-based translator.
  echo          Re-run with:  setup.bat --roman-url ^<zip link^>
)


call :banner "[90/100] Configuration"
set "THREADS=8"
for /f "usebackq delims=" %%C in (`powershell -NoProfile -Command "(Get-CimInstance Win32_ComputerSystem).NumberOfLogicalProcessors"`) do set "THREADS=%%C"
echo threads: %THREADS%  model port: %MODEL_PORT%  api port: %API_PORT%
if not exist ".env" (
  >".env" echo MODEL_BACKEND=qwen_gguf
  >>".env" echo LLAMA_SERVER_URL=http://127.0.0.1:%MODEL_PORT%
  >>".env" echo LLAMA_THREADS=%THREADS%
  echo wrote .env
  set /a NEW_COUNT+=1
) else (
  echo .env already present - left untouched
)
if defined GGUF (
  for %%F in ("!GGUF!") do set "GGUF_NAME=%%~nxF"
  if /i not "!GGUF_NAME!"=="qwen-cpp-review-v3-q4_k_m.gguf" (
    findstr /i /c:"LLAMA_MODEL_PATH" ".env" >nul 2>&1
    if errorlevel 1 (
      >>".env" echo LLAMA_MODEL_PATH=models/gguf/!GGUF_NAME!
      echo added LLAMA_MODEL_PATH=models/gguf/!GGUF_NAME!
    )
  )
)
if not exist "logs" mkdir "logs"


call :banner "[95/100] Verification"
set "CC_FOUND=0"
where g++ >nul 2>&1 && set "CC_FOUND=1"
where clang++ >nul 2>&1 && set "CC_FOUND=1"
where cl >nul 2>&1 && set "CC_FOUND=1"
if "%CC_FOUND%"=="1" (
  echo c++ compiler: found - /optimize can compile and compare rewrites
) else (
  echo c++ compiler: not found - optional, /optimize will answer verified: false
)
if "%SKIP_TESTS%"=="1" goto :tests_skipped
if "%FORCE_TESTS%"=="1" goto :run_tests
if "%PY_CHANGED%"=="1" goto :run_tests
if exist "%STAMP%" goto :tests_cached
goto :run_tests

:run_tests
echo running the test suite...
set "TESTS_RAN=1"
".venv\Scripts\python.exe" -m pytest -q -p no:warnings
if errorlevel 1 (
  echo tests FAILED
  set "TESTS_FAILED=1"
) else (
  >"%STAMP%" echo ok
  echo tests passed - recorded in %STAMP%
)
goto :tests_done

:tests_skipped
echo tests skipped by --skip-tests
goto :tests_done

:tests_cached
echo python packages unchanged and the test suite already passed before
echo nothing new to verify - run setup.bat --test to run them again
:tests_done


echo.
echo ============================================================
echo  [100/100] Summary
echo ============================================================
echo  uv + python 3.11   : ok
echo  dependencies        : ok
set "LINE=  this run          : "
if %NEW_COUNT% EQU 0 (echo %LINE%nothing new to install - all pieces already present) else (echo %LINE%%NEW_COUNT% new items installed)
set "LINE=  llama-server      : "
if "%LLAMA_OK%"=="1" (echo %LINE%ok) else (echo %LINE%MISSING)
set "LINE=  qwen weights      : "
if "%MODEL_OK%"=="1" (echo %LINE%ok) else (echo %LINE%MISSING - see step 65)
set "LINE=  roman urdu model  : "
if "%ROMAN_OK%"=="1" (echo %LINE%ok) else (echo %LINE%missing - optional)
set "LINE=  tests             : "
if "%SKIP_TESTS%"=="1" (echo %LINE%skipped) else if "%TESTS_FAILED%"=="1" (echo %LINE%FAILED) else if "%TESTS_RAN%"=="1" (echo %LINE%ok - passed now) else (echo %LINE%ok - passed earlier, not re-run)
echo.
echo  start everything :  setup.bat start
echo  stop everything  :  setup.bat stop
echo  readiness probe  :  curl -s http://localhost:%API_PORT%/ready
echo ============================================================
if "%TESTS_FAILED%"=="1" exit /b 1

set "ANSWER="
set /p "ANSWER=Start the model server and the API now? [y/N] "
if /i "!ANSWER!"=="y" goto :cmd_start
exit /b 0


:cmd_start
call :banner "Starting services"
call :find_llama
call :find_gguf
if not defined LLAMA_EXE (
  echo llama-server not found. Run setup.bat first.
  exit /b 1
)
if not defined GGUF (
  echo No .gguf under models\gguf. Run setup.bat first.
  exit /b 1
)
set "THREADS=8"
for /f "usebackq delims=" %%C in (`powershell -NoProfile -Command "(Get-CimInstance Win32_ComputerSystem).NumberOfLogicalProcessors"`) do set "THREADS=%%C"

curl.exe -s --max-time 2 "http://127.0.0.1:%MODEL_PORT%/health" | findstr /c:"status" >nul
if not errorlevel 1 (
  echo model server already serving on port %MODEL_PORT%
) else (
  echo starting llama-server on port %MODEL_PORT% ...
  start "llama-server :%MODEL_PORT%" "!LLAMA_EXE!" -m "!GGUF!" --port %MODEL_PORT% -c 4096 -t !THREADS!
)

echo waiting for the model to load
set /a WAITED=0
:wait_model
curl.exe -s --max-time 2 "http://127.0.0.1:%MODEL_PORT%/health" | findstr /c:"ok" >nul
if not errorlevel 1 goto :model_up
set /a WAITED+=5
if %WAITED% GEQ 300 (
  echo model server did not become healthy within 5 minutes.
  echo check the llama-server window, or the port if something else holds %MODEL_PORT%.
  exit /b 1
)
timeout /t 5 /nobreak >nul
goto :wait_model

:model_up
echo model server is up.

curl.exe -s --max-time 2 "http://127.0.0.1:%API_PORT%/health" | findstr /c:"status" >nul
if not errorlevel 1 (
  echo API already serving on port %API_PORT%
  goto :start_done
)
if not exist ".venv\Scripts\python.exe" (
  echo .venv missing. Run setup.bat first.
  exit /b 1
)
echo starting the API on port %API_PORT% ...
start "fyp-api :%API_PORT%" ".venv\Scripts\python.exe" -m uvicorn app.main:app --host 0.0.0.0 --port %API_PORT%

set /a WAITED=0
:wait_api
curl.exe -s --max-time 2 "http://127.0.0.1:%API_PORT%/health" >nul 2>&1
if not errorlevel 1 goto :api_up
set /a WAITED+=2
if %WAITED% GEQ 60 (
  echo API did not answer within 60 seconds. See logs\server.log or the fyp-api window.
  exit /b 1
)
timeout /t 2 /nobreak >nul
goto :wait_api

:api_up
echo API is up.
:start_done
echo.
echo   playground : http://localhost:%API_PORT%/
echo   readiness  : curl -s http://localhost:%API_PORT%/ready
echo   stop all   : setup.bat stop
exit /b 0


:cmd_stop
call :banner "Stopping services"
for %%P in (%MODEL_PORT% %API_PORT%) do (
  powershell -NoProfile -Command "Get-NetTCPConnection -LocalPort %%P -State Listen -ErrorAction SilentlyContinue | ForEach-Object { Stop-Process -Id $_.OwningProcess -Force -ErrorAction SilentlyContinue }" >nul 2>&1
)
if exist ".server.pid" del ".server.pid"
echo stopped anything that was listening on %MODEL_PORT% or %API_PORT%.
exit /b 0


:cmd_status
echo -- model server --
curl.exe -s --max-time 2 "http://127.0.0.1:%MODEL_PORT%/health" & echo.
echo -- API --
curl.exe -s --max-time 2 "http://127.0.0.1:%API_PORT%/ready" & echo.
exit /b 0


:find_llama
set "LLAMA_EXE="
for /f "delims=" %%W in ('where llama-server.exe 2^>nul') do if not defined LLAMA_EXE set "LLAMA_EXE=%%W"
if defined LLAMA_EXE exit /b 0
if exist "%ROOT%tools\llama.cpp\llama-server.exe" set "LLAMA_EXE=%ROOT%tools\llama.cpp\llama-server.exe"
if defined LLAMA_EXE exit /b 0
set "LLAMA_EXE="
for /f "delims=" %%F in ('dir /s /b "%ROOT%tools\llama-server.exe" 2^>nul') do if not defined LLAMA_EXE set "LLAMA_EXE=%%F"
exit /b 0


:add_llama_to_path
for %%F in ("!LLAMA_EXE!") do set "LLAMA_DIR=%%~dpF"
set "PATH=!LLAMA_DIR!;%PATH%"
powershell -NoProfile -Command "$d='!LLAMA_DIR!'; $u=[Environment]::GetEnvironmentVariable('Path','User'); if([string]::IsNullOrEmpty($u)){[Environment]::SetEnvironmentVariable('Path',$d,'User')} elseif($u -notlike ('*' + $d + '*')){[Environment]::SetEnvironmentVariable('Path',($u.TrimEnd(';') + ';' + $d),'User')}" >nul 2>&1
exit /b 0


:find_gguf
set "GGUF="
for %%F in ("%ROOT%models\gguf\*.gguf") do if exist "%%F" set "GGUF=%%F"
exit /b 0


:fetch_gguf
if exist "!MODEL_URL!" (
  echo copying local file !MODEL_URL!
  copy /y "!MODEL_URL!" "%ROOT%models\gguf\" >nul
  if not errorlevel 1 set "MODEL_FETCHED=1"
  exit /b 0
)
set "GGUF_NAME="
for %%F in ("!MODEL_URL!") do set "GGUF_NAME=%%~nxF"
if not defined GGUF_NAME set "GGUF_NAME=qwen-cpp-review-v3-q4_k_m.gguf"
echo downloading !MODEL_URL!
echo this is roughly 1 GB and can take a while.
call :download "!MODEL_URL!" "models\gguf\!GGUF_NAME!"
if not errorlevel 1 set "MODEL_FETCHED=1"
exit /b 0


:find_roman
set "ROMAN_OK="
set "ROMAN_MISSING=0"
for %%F in (config.json generation_config.json model.safetensors tokenizer.json tokenizer_config.json) do (
  if not exist "%ROOT%models\roman-model\t5-stage2-c\%%F" set "ROMAN_MISSING=1"
)
if "%ROMAN_MISSING%"=="0" set "ROMAN_OK=1"
exit /b 0


:fetch_roman
if not exist "models\roman-model\_zip" mkdir "models\roman-model\_zip"
echo downloading !ROMAN_URL!
call :download "!ROMAN_URL!" "models\roman-model\_roman.zip"
if errorlevel 1 exit /b 1
powershell -NoProfile -Command "Expand-Archive -Force -Path '%ROOT%models\roman-model\_roman.zip' -DestinationPath '%ROOT%models\roman-model\_zip'"
del "models\roman-model\_roman.zip"
if exist "%ROOT%models\roman-model\_zip\t5-stage2-c\config.json" (
  xcopy /e /i /y "%ROOT%models\roman-model\_zip\t5-stage2-c" "%ROOT%models\roman-model\t5-stage2-c" >nul
) else if exist "%ROOT%models\roman-model\_zip\config.json" (
  xcopy /e /i /y "%ROOT%models\roman-model\_zip" "%ROOT%models\roman-model\t5-stage2-c" >nul
)
rmdir /s /q "models\roman-model\_zip" 2>nul
call :find_roman
if defined ROMAN_OK set "ROMAN_FETCHED=1"
exit /b 0


:download
echo   %~1
curl.exe -L --fail --retry 3 --retry-delay 2 --connect-timeout 20 -o "%~2.part" "%~1"
if errorlevel 1 (
  echo   download failed: %~1
  if exist "%~2.part" del "%~2.part"
  exit /b 1
)
move /y "%~2.part" "%~2" >nul
exit /b 0


:banner
echo.
echo ============================================================
echo  %~1
echo ============================================================
goto :eof


:fail
echo.
echo SETUP FAILED - see the message above.
pause
exit /b 1


:usage
echo.
echo Usage: setup.bat [action] [options]
echo.
echo Every step checks first: re-running installs only what is still missing
echo and never overwrites something that is already there.
echo.
echo Actions:
echo   setup     install whatever is missing (default)
echo   start     start llama-server and the API, wait until they answer
echo   stop      stop both processes
echo   status    print the model server health and the API readiness probe
echo.
echo Options:
echo   --with-codet5     also install the optional ~2 GB codet5 extra
echo   --vulkan          download the Vulkan build of llama.cpp instead of CPU
echo   --model-url URL   download the Qwen GGUF from a direct link
echo                     (a local file path is copied instead)
echo   --roman-url URL   download the Roman Urdu T5 as a zip archive
echo   --test            run the test suite even if nothing changed
echo   --skip-tests      do not run pytest during setup
echo.
echo Environment variables MODEL_URL and ROMAN_URL work as well.
exit /b 1
