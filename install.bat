@echo off
chcp 65001 >nul
setlocal EnableExtensions EnableDelayedExpansion

title Maya Agent 安装程序
cd /d "%~dp0"

echo ============================================================
echo   Maya Agent 一键安装（优先 mayapy，无需系统 Python）
echo ============================================================
echo   目录: %CD%
echo.

set "TARGET_VER="
set "FORCE_DEPS=0"
for %%A in (%*) do (
  if /I "%%~A"=="uninstall" goto :UNINSTALL
  if /I "%%~A"=="--uninstall" goto :UNINSTALL
  if /I "%%~A"=="force" set "FORCE_DEPS=1"
  if /I "%%~A"=="--force" set "FORCE_DEPS=1"
  if /I "%%~A"=="--force-deps" set "FORCE_DEPS=1"
  if /I not "%%~A"=="force" if /I not "%%~A"=="--force" if /I not "%%~A"=="--force-deps" (
    if not defined TARGET_VER set "TARGET_VER=%%~A"
  )
)
if "%TARGET_VER%"=="" set "TARGET_VER=all"

if not exist "%CD%\maya_agent\__init__.py" (
  echo [错误] 未找到 maya_agent 包，请把本 bat 放在 MayaAgent 项目根目录。
  goto :END_FAIL
)
if not exist "%CD%\scripts\install_engine.py" (
  echo [错误] 未找到 scripts\install_engine.py
  goto :END_FAIL
)

call :RESOLVE_PY
if not defined PYEXE (
  echo [错误] 未找到 mayapy 或系统 Python。
  echo   请安装 Maya，或设置 MAYA_AGENT_MAYAPY_ROOTS 后重试。
  echo   也可打开 Maya，将 install_dragdrop.mel 拖进视口安装。
  goto :END_FAIL
)

echo [1/3] 使用解释器: %PYEXE%
if "!FORCE_DEPS!"=="1" echo      模式: 强制重装依赖 (--force)
if defined MAYA_AGENT_MAYAPY_ROOTS echo      MAYA_AGENT_MAYAPY_ROOTS=%MAYA_AGENT_MAYAPY_ROOTS%
echo.

set "VER_LIST="
if /I not "%TARGET_VER%"=="all" (
  set "VER_LIST=%TARGET_VER%"
) else (
  for /f "usebackq delims=" %%V in (`"%PYEXE%" "%CD%\scripts\maya_discover.py" --print-versions 2^>nul`) do (
    set "VER_LIST=%%V"
  )
)
if "%VER_LIST%"=="" (
  echo [警告] 未自动检测到 Maya，将默认安装到 2025。
  set "VER_LIST=2025"
)

echo [2/3] 目标 Maya 版本: %VER_LIST%
echo.
echo [3/3] 运行安装引擎 …
set "EXTRA="
for %%V in (%VER_LIST%) do set "EXTRA=!EXTRA! --maya-version %%V"
if "!FORCE_DEPS!"=="1" set "EXTRA=!EXTRA! --force-deps"
if exist "%CD%\vendor_cache\" (
  "%PYEXE%" "%CD%\scripts\install_engine.py" --project-root "%CD%" !EXTRA! --vendor-cache "%CD%\vendor_cache"
) else (
  "%PYEXE%" "%CD%\scripts\install_engine.py" --project-root "%CD%" !EXTRA!
)
set "RC=!ERRORLEVEL!"

echo.
echo ============================================================
if !RC! NEQ 0 (
  echo   安装未完全成功 ^(exit !RC!^)
  echo   诊断: "%PYEXE%" "%CD%\scripts\doctor.py"
  echo   或拖入 install_dragdrop.mel
  echo ============================================================
  goto :END_FAIL
)
echo   安装完成 — 请完全退出并重启 Maya
echo   菜单应出现「Maya Agent」，工具架应有「MayaAgent」
echo ============================================================
goto :END_OK


:UNINSTALL
call :RESOLVE_PY
if not defined PYEXE (
  echo [错误] 未找到 mayapy 或系统 Python，无法卸载挂钩。
  goto :END_FAIL
)
echo 使用: %PYEXE%
"%PYEXE%" "%CD%\scripts\install_engine.py" --project-root "%CD%" --uninstall
echo.
echo 卸载完成。请重启 Maya。
goto :END_OK


:RESOLVE_PY
set "PYEXE="
REM 1) mayapy from env roots / common install paths (no system Python needed)
call :FIND_MAYAPY_DIRECT
REM 2) specific version if user passed one
if /I not "%TARGET_VER%"=="" if /I not "%TARGET_VER%"=="all" (
  if not defined PYEXE call :FIND_MAYAPY_FOR %TARGET_VER%
)
REM 3) system python / py launcher
if not defined PYEXE where python >nul 2>&1 && for /f "delims=" %%P in ('where python') do (
  if not defined PYEXE set "PYEXE=%%P"
)
if not defined PYEXE (
  where py >nul 2>&1 && set "PYEXE=py -3"
)
goto :EOF


:FIND_MAYAPY_DIRECT
if defined MAYA_AGENT_MAYAPY_ROOTS (
  for %%R in ("%MAYA_AGENT_MAYAPY_ROOTS:;=" "%") do (
    if not defined PYEXE if exist "%%~R\bin\mayapy.exe" set "PYEXE=%%~R\bin\mayapy.exe"
    if not defined PYEXE if exist "%%~R\mayapy.exe" set "PYEXE=%%~R\mayapy.exe"
  )
)
for %%V in (2026 2025 2024 2023 2022 2020) do (
  if not defined PYEXE call :FIND_MAYAPY_FOR %%V
)
goto :EOF


:FIND_MAYAPY_FOR
set "V=%~1"
if defined PYEXE goto :EOF
if exist "%ProgramFiles%\Autodesk\Maya%V%\bin\mayapy.exe" (
  set "PYEXE=%ProgramFiles%\Autodesk\Maya%V%\bin\mayapy.exe"
  goto :EOF
)
if exist "%ProgramFiles(x86)%\Autodesk\Maya%V%\bin\mayapy.exe" (
  set "PYEXE=%ProgramFiles(x86)%\Autodesk\Maya%V%\bin\mayapy.exe"
  goto :EOF
)
if exist "C:\Program Files\Autodesk\Maya%V%\bin\mayapy.exe" (
  set "PYEXE=C:\Program Files\Autodesk\Maya%V%\bin\mayapy.exe"
  goto :EOF
)
if exist "D:\Program Files\Autodesk\Maya%V%\bin\mayapy.exe" (
  set "PYEXE=D:\Program Files\Autodesk\Maya%V%\bin\mayapy.exe"
  goto :EOF
)
if exist "D:\LAS\LAD\Maya\Program\%V%\Maya%V%\bin\mayapy.exe" (
  set "PYEXE=D:\LAS\LAD\Maya\Program\%V%\Maya%V%\bin\mayapy.exe"
  goto :EOF
)
goto :EOF


:END_OK
echo.
pause
endlocal
exit /b 0

:END_FAIL
echo.
pause
endlocal
exit /b 1
