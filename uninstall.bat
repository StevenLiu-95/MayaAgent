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

echo 将移除:
echo   - userSetup / userSetup.mel 挂钩
echo   - modules\MayaAgent.mod
echo   - Documents\maya\plug-ins\MayaAgent.py
echo   - 工具架偏好 shelf_MayaAgent.mel
echo   - 目录联接 Documents\maya\版本\MayaAgent
echo.

%PYEXE% "%CD%\scripts\install.py" --uninstall
echo.
echo 完成。请重启 Maya。
echo.
echo 若 Maya 当前正在运行，可在 Script Editor 再执行一次即时清理:
echo   import maya_agent
echo   maya_agent.plugin.menu.uninstall_ui()
echo.
pause
endlocal
exit /b 0
