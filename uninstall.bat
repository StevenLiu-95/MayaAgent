@echo off
chcp 65001 >nul
setlocal EnableExtensions
title Maya Agent 卸载
cd /d "%~dp0"

echo ============================================================
echo   Maya Agent 卸载
echo ============================================================
echo.

set "PYEXE="
where python >nul 2>&1 && set "PYEXE=python"
if not defined PYEXE (
  where py >nul 2>&1 && set "PYEXE=py -3"
)
if not defined PYEXE (
  echo [错误] 未找到系统 Python。
  pause
  exit /b 1
)

echo 将移除 userSetup 挂钩与 modules\MayaAgent.mod
echo.
%PYEXE% "%CD%\scripts\install.py" --uninstall
echo.
echo 完成。重启 Maya 后菜单/自动加载即失效。
echo 工具架页签「MayaAgent」如仍在，可在 Maya 中手动删除。
echo.
pause
endlocal
exit /b 0
