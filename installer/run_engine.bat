@echo off
REM Called by Inno Setup — finds mayapy and runs install_engine.py
REM Args forwarded: all args after this script name.
setlocal EnableExtensions EnableDelayedExpansion
set "APP_ROOT=%~dp0.."
REM When installed, this bat lives in {app}\installer\ — project root is parent
for %%I in ("%~dp0..") do set "APP_ROOT=%%~fI"

set "PYEXE="
if defined MAYA_AGENT_MAYAPY_ROOTS (
  for %%R in ("%MAYA_AGENT_MAYAPY_ROOTS:;=" "%") do (
    if not defined PYEXE if exist "%%~R\bin\mayapy.exe" set "PYEXE=%%~R\bin\mayapy.exe"
    if not defined PYEXE if exist "%%~R\mayapy.exe" set "PYEXE=%%~R\mayapy.exe"
  )
)
for %%V in (2026 2025 2024 2023 2022 2020) do (
  if not defined PYEXE if exist "%ProgramFiles%\Autodesk\Maya%%V%\bin\mayapy.exe" (
    set "PYEXE=%ProgramFiles%\Autodesk\Maya%%V%\bin\mayapy.exe"
  )
  if not defined PYEXE if exist "C:\Program Files\Autodesk\Maya%%V%\bin\mayapy.exe" (
    set "PYEXE=C:\Program Files\Autodesk\Maya%%V%\bin\mayapy.exe"
  )
  if not defined PYEXE if exist "D:\LAS\LAD\Maya\Program\%%V%\Maya%%V%\bin\mayapy.exe" (
    set "PYEXE=D:\LAS\LAD\Maya\Program\%%V%\Maya%%V%\bin\mayapy.exe"
  )
)
if not defined PYEXE where python >nul 2>&1 && for /f "delims=" %%P in ('where python') do (
  if not defined PYEXE set "PYEXE=%%P"
)

if not defined PYEXE (
  echo [Maya Agent] ERROR: mayapy / python not found.
  echo Install Maya first, or set MAYA_AGENT_MAYAPY_ROOTS.
  exit /b 1
)

echo [Maya Agent] interpreter: %PYEXE%
echo [Maya Agent] app root: %APP_ROOT%
"%PYEXE%" "%APP_ROOT%\scripts\install_engine.py" --project-root "%APP_ROOT%" %*
exit /b %ERRORLEVEL%
