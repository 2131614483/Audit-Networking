@echo off
REM ============================================================
REM   AI Audit Platform - Start (SAFE EDITION)
REM   no BOM, no unicode, echo( prefix, every path goto :end -> pause
REM ============================================================

setlocal EnableExtensions DisableDelayedExpansion
set "EXITCODE=0"
set "ARGS=%*"

cd /d "%~dp0"
set "BAT_LOG=%~dp0launcher_platform.log"
echo [%date% %time%] started > "%BAT_LOG%"

REM ---- (silent chcp, failure OK) ----
chcp 65001 >nul 2>&1

echo(
echo( ============================================================
echo(     AI Audit Platform - One-Click Launcher
echo(     working dir: %~dp0
echo( ============================================================
echo(

REM ============================================
REM  STEP 1 : venv find / create
REM ============================================
if exist ".venv\Scripts\python.exe" (
    set "PYTHON=%~dp0.venv\Scripts\python.exe"
    echo( [1/4] [OK] venv python found.
    goto :step_install_deps
)

echo( [1/4] [INFO] venv not found, auto-creating ...

where python >nul 2>&1
if %errorlevel%==0 (
    echo(        using system python (may take 10-30s) ...
    python -m venv .venv
    if %errorlevel%==0 if exist ".venv\Scripts\python.exe" (
        set "PYTHON=%~dp0.venv\Scripts\python.exe"
        echo(        [OK] venv created
        goto :step_install_deps
    )
    goto :err_venv_fail
)

where py >nul 2>&1
if %errorlevel%==0 (
    echo(        using py -3 launcher ...
    py -3 -m venv .venv
    if %errorlevel%==0 if exist ".venv\Scripts\python.exe" (
        set "PYTHON=%~dp0.venv\Scripts\python.exe"
        echo(        [OK] venv created
        goto :step_install_deps
    )
    goto :err_venv_fail
)

goto :err_no_python


REM ============================================
REM  STEP 2 : install deps
REM ============================================
:step_install_deps
echo( [2/4] [INFO] checking 3rd-party deps ...
"%PYTHON%" -c "import fastapi, uvicorn, pydantic, yaml, openai" >nul 2>&1
if %errorlevel%==0 (
    echo(        [OK] deps installed, skipping pip.
    goto :step_check_files
)
echo(        [INFO] deps missing, installing requirements.txt ...
echo(        first time may take 1-3 minutes, please wait ...
"%PYTHON%" -m pip install -r requirements.txt
if %errorlevel%==0 (
    echo(        [OK] deps installed
) else (
    echo(        [ERR] pip install FAILED.
    echo(        run manually:
    echo(          "%PYTHON%" -m pip install -r requirements.txt
    set "EXITCODE=4"
    goto :end
)


REM ============================================
REM  STEP 3 : check required files
REM ============================================
:step_check_files
echo( [3/4] [INFO] checking project files ...
if not exist "launch.py" (
    echo(        [ERR] launch.py not found ! cwd=%cd%
    set "EXITCODE=5"
    goto :end
)
if not exist "web\index.html" (
    echo(        [ERR] web\index.html missing !
    set "EXITCODE=6"
    goto :end
)
echo(        [OK] launch.py ............. OK
echo(        [OK] web\index.html ....... OK


REM ============================================
REM  STEP 4 : menu (or pass-through args)
REM ============================================
if defined ARGS if not "%ARGS%"=="" goto :start_with_args

echo( [4/4] Select launch mode:
echo(
echo(        [1] Normal launch (recommended)
echo(        [2] Regen audit data first
echo(        [3] Launch WITHOUT auto-open browser
echo(        [4] Custom port
echo(        [0] Quit
echo(
set /p choice=Enter number [default 1]:
if "%choice%"=="" set choice=1

if "%choice%"=="0" (
    echo( Quitting.
    goto :end
)
if "%choice%"=="1" goto :start
if "%choice%"=="2" ( set "ARGS=--regen" & goto :start )
if "%choice%"=="3" ( set "ARGS=--no-browser" & goto :start )
if "%choice%"=="4" goto :custom_port

echo( [WARN] Invalid input, using [1] Normal launch
goto :start

:custom_port
set /p port=Enter port [default 8765]:
if "%port%"=="" set port=8765
set "ARGS=--port %port%"
goto :start

:start_with_args
echo( [4/4] [INFO] cmd-line args detected: %ARGS%. Launching directly.

:start
echo(
echo( ------------------------------------------------------------
echo(  Starting platform ...
echo(  cmd   = launch.py %ARGS%
echo(  tip   = press Ctrl+C to stop the server
echo( ------------------------------------------------------------
echo(

"%PYTHON%" launch.py %ARGS%
set "EXITCODE=%errorlevel%"
>> "%BAT_LOG%" echo [INFO] launch.py exited code=%EXITCODE%
goto :end


REM ============================================
REM error handlers
REM ============================================
:err_venv_fail
set "EXITCODE=2"
echo(
echo( [ERR] venv creation FAILED.
echo(       Please run manually:
echo(         python -m venv .venv
echo(         .venv\Scripts\python.exe -m pip install -r requirements.txt
goto :end

:err_no_python
set "EXITCODE=3"
echo(
echo( [ERR] Python NOT found on system.
echo(       Install Python 3.10+ ^(check "Add to PATH"^):
echo(       https://www.python.org/downloads/
goto :end


REM ============================================
REM common end: NEVER disappear without user input
REM ============================================
:end
echo(
echo( ------------------------------------------------------------
echo(  Platform stopped.  batch exit code = %EXITCODE%
echo(  batch log: %BAT_LOG%
echo( ------------------------------------------------------------
echo(
echo( Press any key to close this window...
pause >nul
endlocal & exit /b %EXITCODE%
