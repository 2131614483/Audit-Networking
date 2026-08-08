@echo off
REM ============================================================
REM   图形启动器 - SAFE EDITION (no BOM, no unicode, cmd.exe friendly)
REM   Crash-proof: every code path ends in :end -> pause
REM ============================================================

setlocal EnableExtensions DisableDelayedExpansion
set "EXITCODE=0"

cd /d "%~dp0"
set "CRASH_LOG=%~dp0launcher_crash.log"
set "BAT_LOG=%~dp0launcher_batch.log"

REM ---- clear old logs ----
if exist "%CRASH_LOG%" del /q "%CRASH_LOG%" 2>nul
echo [%date% %time%] started > "%BAT_LOG%"
set "PYTHON="

REM ============================================
REM ---- STEP 0:  chcp (silent, may fail)
REM ============================================
chcp 65001 >nul 2>&1
echo(
echo( ============================================================
echo(    AI Audit Platform - GUI Launcher
echo(    dir : %~dp0
echo( ============================================================

REM ============================================
REM ---- STEP 1:  find or create venv
REM ============================================
if exist ".venv\Scripts\python.exe" (
    set "PYTHON=%~dp0.venv\Scripts\python.exe"
    echo( [OK] venv python found
    echo(      path = %PYTHON%
    goto :step2
)

echo( [INFO] venv NOT found. Attempting auto-create...
>> "%BAT_LOG%" echo [INFO] auto-create venv starting...

REM ---- try python.exe first ----
where python >nul 2>&1
if %errorlevel%==0 (
    echo( [INFO] using system "python" to build venv (~10-30s) ...
    python -m venv .venv
    if %errorlevel%==0 if exist ".venv\Scripts\python.exe" (
        set "PYTHON=%~dp0.venv\Scripts\python.exe"
        echo( [OK] venv created.
        goto :step2
    )
    goto :err_venv_fail
)

REM ---- fallback: py launcher ----
where py >nul 2>&1
if %errorlevel%==0 (
    echo( [INFO] using "py -3" to build venv ...
    py -3 -m venv .venv
    if %errorlevel%==0 if exist ".venv\Scripts\python.exe" (
        set "PYTHON=%~dp0.venv\Scripts\python.exe"
        echo( [OK] venv created.
        goto :step2
    )
    goto :err_venv_fail
)

goto :err_no_python


REM ============================================
REM ---- STEP 2:  start launcher_gui.py
REM ============================================
:step2
if not exist "launcher_gui.py" (
    echo( [ERR] missing launcher_gui.py in %cd%
    set "EXITCODE=4"
    goto :end
)

echo( [INFO] launching GUI (please wait) ...
>> "%BAT_LOG%" echo [INFO] cmd = "%PYTHON%" "%~dp0launcher_gui.py"

"%PYTHON%" "%~dp0launcher_gui.py"
set "EXITCODE=%errorlevel%"
>> "%BAT_LOG%" echo [INFO] launcher_gui.py exited code=%EXITCODE%


REM ============================================
REM ---- result report
REM ============================================
echo(
echo( ------------------------------------------------------------
if "%EXITCODE%"=="0" (
    echo( [OK] GUI launcher exited normally.
) else (
    echo( [ERR] GUI exited with ERROR code %EXITCODE%
    if exist "%CRASH_LOG%" (
        echo(
        echo( ===== launcher_crash.log (tail 60) =====
        powershell -NoProfile -NonInteractive -Command "Get-Content '%CRASH_LOG%' -Tail 60"
        echo( ===== end of crash log =====
        echo(
        echo( Full crash log : %CRASH_LOG%
    ) else (
        echo( [WARN] no crash.log. Check launcher_batch.log below.
        if exist "%BAT_LOG%" (
            echo( ===== launcher_batch.log =====
            type "%BAT_LOG%"
            echo( ===== end =====
        )
    )
)
echo( ------------------------------------------------------------
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
echo( [ERR] Python not installed.
echo(       Install Python 3.10+ ^(check "Add to PATH"^):
echo(       https://www.python.org/downloads/
goto :end


REM ============================================
REM common exit - always PAUSE, never close
REM ============================================
:end
echo(
echo( Press any key to close this window...
pause >nul
endlocal & exit /b %EXITCODE%
