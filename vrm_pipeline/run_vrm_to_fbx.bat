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
:: Batch-converts .vrm files to Cascadeur-ready .fbx using Blender + ARP.
::
:: Usage:
::     run_vrm_to_fbx.bat [--headless] [INPUT_DIR] [OUTPUT_DIR]
::
:: Flags:
::     --headless   Run Blender in background mode (no GUI).
::                  Must be the FIRST argument if used.
::                  WARNING: ARP operators require UI mode. Headless
::                  mode will skip ARP and move files to failed.
::
:: Default (no flag) runs Blender with full UI, which is required
:: for Auto-Rig Pro operators to function.
::
:: Defaults (no arguments):
::     INPUT_DIR  = <script_dir>\vrm_in     (fallback: parent\vrm_in)
::     OUTPUT_DIR = <script_dir>\fbx_out    (fallback: parent\fbx_out)
::     DONE_DIR   = <script_dir>\vrm_done   (fallback: parent\vrm_done)
::     FAILED_DIR = <script_dir>\vrm_failed (fallback: parent\vrm_failed)
:: =========================================================================

:: ---- Create timestamped log file (locale-independent via PowerShell) ----
for /f %%I in ('powershell -NoProfile -Command "Get-Date -Format yyyyMMdd_HHmmss"') do set "LOGSTAMP=%%I"
set "LOGFILE=%~dp0bat_debug_log_!LOGSTAMP!.txt"

:: Initialise the log file
echo.> "!LOGFILE!"

:: ---- Helper subroutine: log to both console and file ----
:: Use "call :LOG message" throughout the script.
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
    echo ERROR: Blender not found at: !BLENDER_EXE!
    echo ERROR: Blender not found at: !BLENDER_EXE!>> "!LOGFILE!"
    pause
    exit /b 9009
)

:: ==== 3. Resolve script directory and default folders ====
set "SCRIPT_DIR=%~dp0"
set "INPUT_DIR=!SCRIPT_DIR!vrm_in"
set "OUTPUT_DIR=!SCRIPT_DIR!fbx_out"
set "DONE_DIR=!SCRIPT_DIR!vrm_done"
set "FAILED_DIR=!SCRIPT_DIR!vrm_failed"

:: ---- Parse --headless flag (must be first argument if used) ----
:: DEFAULT: UI mode (no --background flag)
set "HEADLESS="
if /i "%~1"=="--headless" (
    set "HEADLESS=--background"
    shift
)

:: ---- Override INPUT_DIR / OUTPUT_DIR from arguments if provided ----
if not "%~1"=="" set "INPUT_DIR=%~1"
if not "%~2"=="" set "OUTPUT_DIR=%~2"

:: ==== 4. Parent folder fallback ====
:: If default folder does not exist but parent-level folder does, use parent.
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

:: ==== 6. Print resolved paths BEFORE running Blender ====
:: Using direct echo with delayed expansion (most reliable for paths).
call :LOG "--- Resolved Paths ---"
echo BLENDER_EXE=!BLENDER_EXE!
echo BLENDER_EXE=!BLENDER_EXE!>> "!LOGFILE!"
echo SCRIPT_DIR=!SCRIPT_DIR!
echo SCRIPT_DIR=!SCRIPT_DIR!>> "!LOGFILE!"
echo INPUT_DIR=!INPUT_DIR!
echo INPUT_DIR=!INPUT_DIR!>> "!LOGFILE!"
echo OUTPUT_DIR=!OUTPUT_DIR!
echo OUTPUT_DIR=!OUTPUT_DIR!>> "!LOGFILE!"
echo DONE_DIR=!DONE_DIR!
echo DONE_DIR=!DONE_DIR!>> "!LOGFILE!"
echo FAILED_DIR=!FAILED_DIR!
echo FAILED_DIR=!FAILED_DIR!>> "!LOGFILE!"
call :LOG ""

:: ==== 7. Validate Python script ====
set "PYTHON_SCRIPT=!SCRIPT_DIR!vrm_to_fbx_batch.py"
if not exist "!PYTHON_SCRIPT!" (
    echo ERROR: Python script not found: !PYTHON_SCRIPT!
    echo ERROR: Python script not found: !PYTHON_SCRIPT!>> "!LOGFILE!"
    pause
    exit /b 2
)

:: ---- Count VRM files ----
set "VRM_COUNT=0"
for %%F in ("!INPUT_DIR!\*.vrm") do set /a VRM_COUNT+=1

call :LOG "VRM files found: !VRM_COUNT!"

if !VRM_COUNT! equ 0 (
    call :LOG "No .vrm files found in: !INPUT_DIR!"
    call :LOG ""
    call :LOG "Place your .vrm files there and run this script again."
    set "EXIT_CODE=0"
    goto :end
)

call :LOG ""

:: ---- Launch mode message ----
:: NOTE: Using goto instead of if/else to avoid CMD parsing ')' inside
:: quoted strings as block-closers.
if defined HEADLESS goto :mode_headless
call :LOG "============================================================="
call :LOG "  MODE: UI (default)"
call :LOG "  Blender will open with a visible window."
call :LOG "  This is REQUIRED for Auto-Rig Pro operators."
call :LOG "============================================================="
goto :mode_done
:mode_headless
call :LOG "============================================================="
call :LOG "  MODE: HEADLESS (--background)"
call :LOG "  WARNING: ARP operators will NOT work in this mode."
call :LOG "  Files requiring ARP will be moved to the failed folder."
call :LOG "  Remove --headless flag to enable ARP processing."
call :LOG "============================================================="
:mode_done
call :LOG ""

:: ==== 8. Build and execute Blender command ====
call :LOG "--- Blender Command ---"

:: NOTE: Using goto to avoid ')' in echo strings breaking CMD block parsing.
if defined HEADLESS goto :cmd_headless

:: --- UI mode: no --background ---
echo "!BLENDER_EXE!" --python "!PYTHON_SCRIPT!" -- "!INPUT_DIR!" "!OUTPUT_DIR!" "!DONE_DIR!" "!FAILED_DIR!"
echo "!BLENDER_EXE!" --python "!PYTHON_SCRIPT!" -- "!INPUT_DIR!" "!OUTPUT_DIR!" "!DONE_DIR!" "!FAILED_DIR!">> "!LOGFILE!"
call :LOG ""
"!BLENDER_EXE!" --python "!PYTHON_SCRIPT!" -- "!INPUT_DIR!" "!OUTPUT_DIR!" "!DONE_DIR!" "!FAILED_DIR!"
goto :cmd_done

:cmd_headless
:: --- Headless mode: with --background ---
echo "!BLENDER_EXE!" --background --python "!PYTHON_SCRIPT!" -- "!INPUT_DIR!" "!OUTPUT_DIR!" "!DONE_DIR!" "!FAILED_DIR!"
echo "!BLENDER_EXE!" --background --python "!PYTHON_SCRIPT!" -- "!INPUT_DIR!" "!OUTPUT_DIR!" "!DONE_DIR!" "!FAILED_DIR!">> "!LOGFILE!"
call :LOG ""
"!BLENDER_EXE!" --background --python "!PYTHON_SCRIPT!" -- "!INPUT_DIR!" "!OUTPUT_DIR!" "!DONE_DIR!" "!FAILED_DIR!"

:cmd_done
set "EXIT_CODE=!ERRORLEVEL!"

call :LOG ""
call :LOG "Blender exited with code: !EXIT_CODE!"
call :LOG "====================================================================="

:: ---- Exit-code summary ----
:: NOTE: Using goto instead of if/else to avoid ')' in messages breaking
:: CMD block parsing.
if !EXIT_CODE! equ 0 goto :result_ok
if !EXIT_CODE! equ 2 goto :result_partial
goto :result_error

:result_ok
call :LOG "  Pipeline completed successfully. All files processed."
goto :result_done

:result_partial
call :LOG "  Pipeline completed with some failures."
goto :result_done

:result_error
call :LOG "  Pipeline encountered a critical error - exit code: !EXIT_CODE!"
call :LOG "  Check console output above for details."

:result_done
call :LOG "====================================================================="
call :LOG ""
echo   Done folder:   !DONE_DIR!
echo   Done folder:   !DONE_DIR!>> "!LOGFILE!"
echo   Failed folder: !FAILED_DIR!
echo   Failed folder: !FAILED_DIR!>> "!LOGFILE!"
echo   Output folder: !OUTPUT_DIR!
echo   Output folder: !OUTPUT_DIR!>> "!LOGFILE!"
call :LOG ""
call :LOG "Done."

:end
call :LOG ""
call :LOG "Script finished. Exit code: !EXIT_CODE!"
call :LOG "Log saved to: !LOGFILE!"
echo.
echo Press any key to close this window...
pause >nul
exit /b !EXIT_CODE!
