@echo off
chcp 65001 >nul
setlocal enabledelayedexpansion

rem ==========================================================================
rem  dfmap export  ->  Unreal Engine 5.3.2  one-click import
rem  usage:  ue_import.bat "F:\exports\Mogadishu_20261101_0736" [--use-scene-json] [--level LV_x]
rem  env  :  UE_ROOT=D:\UE_5.3   UE_PROJECT=D:\MyProj\MyProj.uproject
rem ==========================================================================

set "SPLIT=%~1"
if "%SPLIT%"=="" (
  echo usage: ue_import.bat "export dir" [--use-scene-json] [--level LV_xxx]
  exit /b 1
)
if not exist "%SPLIT%" (
  echo [x] export dir not found: %SPLIT%
  exit /b 1
)

rem map name from the export dir (before any shift)
for %%I in ("%SPLIT%") do set "MAP=%%~nxI"
set "PARENT=%~dp1"
shift

if "%UE_ROOT%"=="" set "UE_ROOT=E:\UE_5.3"
set "UE_CMD=%UE_ROOT%\Engine\Binaries\Win64\UnrealEditor-Cmd.exe"
if not exist "%UE_CMD%" (
  echo [x] UnrealEditor-Cmd.exe not found: %UE_CMD%
  echo     set UE_ROOT to your UE 5.3.2 install dir.
  exit /b 1
)

if "%UE_PROJECT%"=="" (
  echo [x] set UE_PROJECT to your .uproject, e.g.
  echo     set UE_PROJECT=D:\MyUE53\MyProject.uproject
  exit /b 1
)
if not exist "%UE_PROJECT%" (
  echo [x] project not found: %UE_PROJECT%
  exit /b 1
)

set "SCRIPT=%~dp0ue_import_dfmap.py"
if not exist "%SCRIPT%" (
  echo [x] script not found: %SCRIPT%
  exit /b 1
)

set "LOG=%PARENT%ue_import.log"
echo [i] engine : %UE_CMD%
echo [i] project: %UE_PROJECT%
echo [i] input  : %SPLIT%
echo [i] dest   : /Game/AtlasMaps/%MAP%   level: LV_%MAP%
echo [i] log    : %LOG%
echo.

"%UE_CMD%" "%UE_PROJECT%" -run=pythonscript -script="%SCRIPT%" -- --split "%SPLIT%" --dest "/Game/AtlasMaps/%MAP%" --level "LV_%MAP%" %* -unattended -nopause -nosplash -nullrhi -stdout > "%LOG%" 2>&1

set "RC=%ERRORLEVEL%"
echo.
echo [i] exit code: %RC%
echo ---- tail of log ----
powershell -NoProfile -Command "Get-Content -LiteralPath '%LOG%' -Tail 40"
echo ---------------------
endlocal & exit /b %RC%
