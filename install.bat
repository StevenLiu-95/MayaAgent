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

REM ---- 可选参数: 2025 / all / uninstall / force ----
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

REM ---- 检查项目文件 ----
if not exist "%CD%\maya_agent\__init__.py" (
  echo [错误] 未找到 maya_agent 包，请把本 bat 放在 MayaAgent 项目根目录。
  goto :END_FAIL
)
if not exist "%CD%\scripts\install.py" (
  echo [错误] 未找到 scripts\install.py
  goto :END_FAIL
)
if not exist "%CD%\scripts\install_deps.py" (
  echo [错误] 未找到 scripts\install_deps.py
  goto :END_FAIL
)
if not exist "%CD%\requirements.txt" (
  echo [错误] 未找到 requirements.txt
  goto :END_FAIL
)
if not exist "%CD%\config\default_config.json" (
  echo [警告] 缺少 config\default_config.json，将尝试继续…
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
if "!FORCE_DEPS!"=="1" echo      模式: 强制重装依赖 (--force)
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
    if exist "D:\LAS\LAD\Maya\Program\%%V\Maya%%V\bin\mayapy.exe" set "HIT=1"
    if exist "C:\Program Files\Autodesk\Maya%%V\bin\mayapy.exe" set "HIT=1"
    if !HIT! EQU 1 set "VER_LIST=!VER_LIST! %%V"
  )
)

if "%VER_LIST%"=="" (
  echo [警告] 未自动检测到 Maya，将默认安装到 2025。
  set "VER_LIST=2025"
)

echo [2/4] 目标 Maya 版本:%VER_LIST%
echo.

REM ---- 为每个版本安装 mayapy 依赖（代理 / 镜像 / 逐包 / .vendor 兜底）----
echo [3/4] 安装 Python 依赖到各版本 mayapy ...
set "DEP_ARGS="
for %%V in (%VER_LIST%) do (
  set "DEP_ARGS=!DEP_ARGS! --maya-version %%V"
)
if "!FORCE_DEPS!"=="1" set "DEP_ARGS=!DEP_ARGS! --force"
%PYEXE% "%CD%\scripts\install_deps.py" !DEP_ARGS!
set "DEP_RC=!ERRORLEVEL!"
if !DEP_RC! NEQ 0 (
  echo.
  echo   [警告] 部分 mayapy 依赖安装失败。
  echo          将尝试仅写入项目 .vendor 兜底目录 …
  %PYEXE% "%CD%\scripts\install_deps.py" --vendor-only
  if !ERRORLEVEL! EQU 0 (
    echo   [成功] .vendor 已就绪；Maya Agent 启动时会自动注入该路径。
  ) else (
    echo   [警告] .vendor 也失败。菜单仍可出现；对话需要 httpx。
    echo          可稍后执行: install.bat force
  )
) else (
  echo   [成功] 依赖检查通过。
)

echo.
echo [4/4] 写入 userSetup / modules / 目录联接 ...
set "HOOK_FAIL=0"
for %%V in (%VER_LIST%) do (
  echo   - 配置 Maya %%V
  %PYEXE% "%CD%\scripts\install.py" --maya-version %%V --skip-deps
  if !ERRORLEVEL! NEQ 0 (
    echo     [失败] Maya %%V 配置出错
    set "HOOK_FAIL=1"
  ) else (
    echo     [成功] Maya %%V
  )
)

echo.
echo ============================================================
echo   安装完成
echo ============================================================
echo   请完全退出并重启 Maya，然后检查:
echo     1. 顶部菜单是否有「Maya Agent」
echo     2. 工具架是否有「MayaAgent」页签
echo     3. 对话前确认 Script Editor 无 ModuleNotFoundError: httpx
echo.
echo   若依赖仍缺，任选其一:
echo     A. install.bat force
echo     B. python scripts\install_deps.py --force
echo     C. python scripts\install_deps.py --vendor-only
echo.
echo   若菜单仍未出现，任选其一:
echo     A. 把项目根目录的 install_dragdrop.mel 拖进 Maya 视口
echo     B. 在 Script Editor ^(Python^) 执行:
echo          import maya_agent
echo          maya_agent.reload()
echo.
echo   卸载请双击: uninstall.bat
echo ============================================================
if "!HOOK_FAIL!"=="1" goto :END_FAIL
if !DEP_RC! NEQ 0 (
  REM 挂钩成功但依赖有警告时仍视为可用安装
  goto :END_OK
)
goto :END_OK


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
%PYEXE% "%CD%\scripts\install.py" --uninstall --skip-deps
echo.
echo 卸载完成。如需删除 Documents\maya\版本\MayaAgent 联接目录，可手动删除。
echo 项目 .vendor 目录如需清理可手动删除。
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
