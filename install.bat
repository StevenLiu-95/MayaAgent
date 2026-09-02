@echo off
chcp 65001 >nul
setlocal EnableExtensions EnableDelayedExpansion

title Maya Agent 安装程序
cd /d "%~dp0"

echo ============================================================
echo   Maya Agent 一键安装
echo ============================================================
echo   目录: %CD%
echo.

REM ---- 可选参数: 2025 / all / uninstall ----
set "TARGET_VER=%~1"
if /I "%TARGET_VER%"=="uninstall" goto :UNINSTALL
if /I "%TARGET_VER%"=="--uninstall" goto :UNINSTALL
if "%TARGET_VER%"=="" set "TARGET_VER=all"

REM ---- 检查项目文件 ----
if not exist "%CD%\maya_agent\__init__.py" (
  echo [错误] 未找到 maya_agent 包，请把本 bat 放在 MayaAgent 项目根目录。
  goto :END_FAIL
)
if not exist "%CD%\scripts\install.py" (
  echo [错误] 未找到 scripts\install.py
  goto :END_FAIL
)
if not exist "%CD%\requirements.txt" (
  echo [错误] 未找到 requirements.txt
  goto :END_FAIL
)

REM ---- 找 Python（优先系统 python，其次 py launcher）----
set "PYEXE="
where python >nul 2>&1 && set "PYEXE=python"
if not defined PYEXE (
  where py >nul 2>&1 && set "PYEXE=py -3"
)
if not defined PYEXE (
  echo [错误] 未找到系统 Python。请先安装 Python 3，或确认 python 在 PATH 中。
  goto :END_FAIL
)

echo [1/4] 使用解释器: %PYEXE%
echo.

REM ---- 收集要安装的 Maya 版本 ----
set "VER_LIST="
if /I not "%TARGET_VER%"=="all" (
  set "VER_LIST=%TARGET_VER%"
) else (
  for %%V in (2020 2022 2023 2024 2025 2026) do (
    set "HIT=0"
    if exist "%USERPROFILE%\Documents\maya\%%V" set "HIT=1"
    reg query "HKLM\SOFTWARE\Autodesk\Maya\%%V\Setup\InstallPath" >nul 2>&1 && set "HIT=1"
    if !HIT! EQU 1 set "VER_LIST=!VER_LIST! %%V"
  )
)

if "%VER_LIST%"=="" (
  echo [警告] 未自动检测到 Maya，将默认安装到 2025。
  set "VER_LIST=2025"
)

echo [2/4] 目标 Maya 版本:%VER_LIST%
echo.

REM ---- 为每个版本安装 mayapy 依赖 ----
echo [3/4] 安装 Python 依赖到各版本 mayapy ...
set "REQ_TMP=%TEMP%\maya_agent_requirements.txt"
copy /Y "%CD%\requirements.txt" "%REQ_TMP%" >nul

for %%V in (%VER_LIST%) do (
  call :INSTALL_DEPS %%V
)

echo.
echo [4/4] 写入 userSetup / modules / 目录联接 ...
for %%V in (%VER_LIST%) do (
  echo   - 配置 Maya %%V
  %PYEXE% "%CD%\scripts\install.py" --maya-version %%V
  if !ERRORLEVEL! NEQ 0 (
    echo     [失败] Maya %%V 配置出错
  ) else (
    echo     [成功] Maya %%V
  )
)

echo.
echo ============================================================
echo   安装完成
echo ============================================================
echo   请重启 Maya，然后检查:
echo     1. 顶部菜单是否有「Maya Agent」
echo     2. 工具架是否有「MayaAgent」页签
echo.
echo   若菜单未出现，在 Script Editor 执行:
echo     import maya_agent
echo     maya_agent.plugin.menu._deferred_install()
echo.
echo   卸载请双击: uninstall.bat
echo ============================================================
goto :END_OK


:INSTALL_DEPS
set "VER=%~1"
set "MAYAPY="

REM 1) 注册表
for /f "tokens=2*" %%A in ('reg query "HKLM\SOFTWARE\Autodesk\Maya\%VER%\Setup\InstallPath" /v MAYA_INSTALL_LOCATION 2^>nul') do (
  set "MAYAROOT=%%B"
)
if defined MAYAROOT (
  if exist "!MAYAROOT!bin\mayapy.exe" set "MAYAPY=!MAYAROOT!bin\mayapy.exe"
  if exist "!MAYAROOT!\bin\mayapy.exe" set "MAYAPY=!MAYAROOT!\bin\mayapy.exe"
)

REM 2) 常见路径兜底
if not defined MAYAPY if exist "C:\Program Files\Autodesk\Maya%VER%\bin\mayapy.exe" (
  set "MAYAPY=C:\Program Files\Autodesk\Maya%VER%\bin\mayapy.exe"
)
if not defined MAYAPY if exist "D:\Program Files\Autodesk\Maya%VER%\bin\mayapy.exe" (
  set "MAYAPY=D:\Program Files\Autodesk\Maya%VER%\bin\mayapy.exe"
)

if not defined MAYAPY (
  echo   [跳过] Maya %VER% 未找到 mayapy.exe，仅写入脚本挂钩。
  set "MAYAROOT="
  goto :EOF
)

echo   [依赖] Maya %VER%
echo          %MAYAPY%
"%MAYAPY%" -m pip install -r "%REQ_TMP%"
if !ERRORLEVEL! NEQ 0 (
  echo   [警告] Maya %VER% 依赖安装失败，可稍后手动执行:
  echo          "%MAYAPY%" -m pip install -r requirements.txt
) else (
  echo   [成功] Maya %VER% 依赖已就绪
)
set "MAYAROOT="
set "MAYAPY="
goto :EOF


:UNINSTALL
echo ============================================================
echo   Maya Agent 卸载
echo ============================================================
set "PYEXE="
where python >nul 2>&1 && set "PYEXE=python"
if not defined PYEXE where py >nul 2>&1 && set "PYEXE=py -3"
if not defined PYEXE (
  echo [错误] 未找到 Python
  goto :END_FAIL
)
%PYEXE% "%CD%\scripts\install.py" --uninstall
echo.
echo 卸载完成。如需删除 Documents\maya\版本\MayaAgent 联接目录，可手动删除。
goto :END_OK


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
