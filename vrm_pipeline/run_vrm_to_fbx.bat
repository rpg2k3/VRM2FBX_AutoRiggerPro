@echo off
:: =========================================================================
:: PERSISTENT-WINDOW WRAPPER
:: When double-clicked, re-launch inside a cmd.exe /k window so the
:: console never closes automatically.
:: =========================================================================
if /i not "%~1"=="--persist" (
    start "VRM2FBX" cmd.exe /k ""%~f0" --persist %*"
    exit /b
)
:: Strip the --persist flag so the rest of the script sees real args only
shift

setlocal EnableExtensions EnableDelayedExpansion
title VRM2FBX AutoRig

:: =========================================================================
:: run_vrm_to_fbx.bat
:: =========================================================================
:: Batch-converts .vrm files to .fbx (embedded textures) + .glb + .dae + .obj using Blender + ARP.
::
:: Usage:
::     run_vrm_to_fbx.bat [--headless] [INPUT_DIR] [OUTPUT_DIR]
::
:: Flags:
::     --headless   Run Blender in background mode (no GUI).
::                  Must be the FIRST argument if used.
::                  Python script is told via 5th argument; ARP may be skipped.
::                  Fallback conversion-only export still produces FBX when possible.
::
:: Default (no flag) runs Blender with full UI for Auto-Rig Pro.
::
:: Defaults (no arguments):
::     INPUT_DIR  = <script_dir>\vrm_in     (fallback: parent\vrm_in)
::     OUTPUT_DIR = <script_dir>\fbx_out    (fallback: parent\fbx_out)
::     DONE_DIR   = <script_dir>\vrm_done   (fallback: parent\vrm_done)
::     FAILED_DIR = <script_dir>\vrm_failed (fallback: parent\vrm_failed)
::
:: Exit codes: 0 = all succeeded, 2 = some failed, 1 = fatal (script cannot run)
:: =========================================================================

:: ---- Create timestamped log file (locale-independent via PowerShell) ----
for /f %%I in ('powershell -NoProfile -Command "Get-Date -Format yyyyMMdd_HHmmss"') do set "LOGSTAMP=%%I"
set "LOGFILE=%~dp0bat_debug_log_!LOGSTAMP!.txt"

:: Initialise the log file
echo.> "!LOGFILE!"

:: ---- Helper subroutine: log to both console and file ----
goto :AFTER_LOG_FUNC
:LOG
set "LOGMSG=%~1"
if not defined LOGMSG (
    echo.
    echo.>> "!LOGFILE!"
    goto :eof
)
echo !LOGMSG!
echo !LOGMSG!>> "!LOGFILE!"
goto :eof
:AFTER_LOG_FUNC

call :LOG "============================================================="
call :LOG "  VRM2FBX AutoRig - BAT Debug Log"
call :LOG "  Started: %DATE% %TIME%"
call :LOG "  Log file: !LOGFILE!"
call :LOG "============================================================="
call :LOG ""

:: ==== 1. Hardcode Blender exe path ====
set "BLENDER_EXE=D:\DevTools\blender 4.1\blender-4.1.1-windows-x64\blender.exe"

:: ==== 2. Validate Blender exe ====
if not exist "!BLENDER_EXE!" (
    call :LOG "ERROR: Blender not found at: !BLENDER_EXE!"
    pause
    exit /b 1
)

:: ==== 3. Resolve script directory and default folders ====
set "SCRIPT_DIR=%~dp0"
if "!SCRIPT_DIR!"=="" set "SCRIPT_DIR=%CD%\"
set "INPUT_DIR=!SCRIPT_DIR!vrm_in"
set "INPUT_DIR_ALT=!SCRIPT_DIR!..\vrm_in"
for %%I in ("!INPUT_DIR_ALT!") do set "INPUT_DIR_ALT=%%~fI"
set "OUTPUT_DIR=!SCRIPT_DIR!fbx_out"
set "DONE_DIR=!SCRIPT_DIR!vrm_done"
set "FAILED_DIR=!SCRIPT_DIR!vrm_failed"

:: ---- Parse --headless flag (must be first argument if used) ----
set "HEADLESS="
if /i "%~1"=="--headless" (
    set "HEADLESS=1"
    shift
)

:: ---- Override INPUT_DIR / OUTPUT_DIR from arguments if provided ----
if not "%~1"=="" set "INPUT_DIR=%~1" & set "INPUT_DIR_USER_SET=1"
if not "%~2"=="" set "OUTPUT_DIR=%~2"

:: ==== 4. Parent folder fallback ====
set "PARENT_DIR=!SCRIPT_DIR!.."
if not exist "!INPUT_DIR!"  if exist "!PARENT_DIR!\vrm_in"     set "INPUT_DIR=!PARENT_DIR!\vrm_in"
if not exist "!OUTPUT_DIR!" if exist "!PARENT_DIR!\fbx_out"    set "OUTPUT_DIR=!PARENT_DIR!\fbx_out"
if not exist "!DONE_DIR!"   if exist "!PARENT_DIR!\vrm_done"   set "DONE_DIR=!PARENT_DIR!\vrm_done"
if not exist "!FAILED_DIR!" if exist "!PARENT_DIR!\vrm_failed" set "FAILED_DIR=!PARENT_DIR!\vrm_failed"

:: ==== 5. Create resolved folders ====
mkdir "!INPUT_DIR!" 2>nul
mkdir "!OUTPUT_DIR!" 2>nul
mkdir "!DONE_DIR!" 2>nul
mkdir "!FAILED_DIR!" 2>nul

:: ==== 6. Print resolved paths ====
call :LOG "--- Resolved Paths ---"
call :LOG "INPUT_DIR=!INPUT_DIR!"
call :LOG "OUTPUT_DIR=!OUTPUT_DIR!"
call :LOG "DONE_DIR=!DONE_DIR!"
call :LOG "FAILED_DIR=!FAILED_DIR!"
call :LOG ""

:: ==== 7. Validate Python script ====
set "PYTHON_SCRIPT=!SCRIPT_DIR!vrm_to_fbx_batch.py"
if not exist "!PYTHON_SCRIPT!" (
    call :LOG "ERROR: Python script not found: !PYTHON_SCRIPT!"
    pause
    exit /b 1
)

:: ---- Count VRM files; fallback to project root vrm_in if default has 0 ----
set "VRM_COUNT=0"
for %%F in ("!INPUT_DIR!\*.vrm") do set /a VRM_COUNT+=1
if !VRM_COUNT! equ 0 if not defined INPUT_DIR_USER_SET (
    set "VRM_ALT=0"
    for %%F in ("!INPUT_DIR_ALT!\*.vrm") do set /a VRM_ALT+=1
    if !VRM_ALT! gtr 0 (
        set "INPUT_DIR=!INPUT_DIR_ALT!"
        set "VRM_COUNT=!VRM_ALT!"
        call :LOG "No VRMs in default folder; using project root vrm_in."
    )
)
call :LOG "Using input folder: !INPUT_DIR!"
call :LOG "VRM files found: !VRM_COUNT!"

if !VRM_COUNT! equ 0 (
    call :LOG "No .vrm files found in: !INPUT_DIR!"
    call :LOG "Place your .vrm files there and run this script again."
    set "EXIT_CODE=0"
    goto :summary
)

:: ---- Mode and exact Blender command (build display string, then run) ----
set "CMD_LOG=!BLENDER_EXE!"
if defined HEADLESS (
    call :LOG "MODE: HEADLESS (Blender --background, script receives --headless)"
    set "CMD_LOG=!CMD_LOG! --background --python "!PYTHON_SCRIPT!""
    set "CMD_LOG=!CMD_LOG! -- "!INPUT_DIR!" "!OUTPUT_DIR!" "!DONE_DIR!" "!FAILED_DIR!" --headless"
) else (
    call :LOG "MODE: UI (default, no --background)"
    set "CMD_LOG=!CMD_LOG! --python "!PYTHON_SCRIPT!""
    set "CMD_LOG=!CMD_LOG! -- "!INPUT_DIR!" "!OUTPUT_DIR!" "!DONE_DIR!" "!FAILED_DIR!"
)
call :LOG "--- Exact Blender command ---"
call :LOG "!CMD_LOG!"
call :LOG ""

:: ==== 8. Execute Blender ====
if defined HEADLESS (
    "!BLENDER_EXE!" --background --python "!PYTHON_SCRIPT!" -- "!INPUT_DIR!" "!OUTPUT_DIR!" "!DONE_DIR!" "!FAILED_DIR!" --headless
) else (
    "!BLENDER_EXE!" --python "!PYTHON_SCRIPT!" -- "!INPUT_DIR!" "!OUTPUT_DIR!" "!DONE_DIR!" "!FAILED_DIR!"
)
set "EXIT_CODE=!ERRORLEVEL!"

:: ---- Normalize exit: 0 = success, 2 = partial, 1 = fatal ----
if !EXIT_CODE! equ 0 goto :summary
if !EXIT_CODE! equ 2 goto :summary
set "EXIT_CODE=1"

:summary
call :LOG "============================================================="
if !EXIT_CODE! equ 0 call :LOG "  Result: All files processed successfully."
if !EXIT_CODE! equ 2 call :LOG "  Result: Some files failed (see pipeline log)."
if !EXIT_CODE! equ 1 call :LOG "  Result: Fatal error (exit code: !EXIT_CODE!)."
call :LOG "  Done folder:   !DONE_DIR!"
call :LOG "  Failed folder: !FAILED_DIR!"
call :LOG "  Output folder: !OUTPUT_DIR!"
call :LOG "  Script finished. Exit code: !EXIT_CODE!"
call :LOG "  Log saved to: !LOGFILE!"
call :LOG "============================================================="
echo.
echo Press any key to close this window...
pause >nul
exit /b !EXIT_CODE!
