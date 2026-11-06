@echo off
chcp 65001 >nul
setlocal EnableExtensions EnableDelayedExpansion

title Maya Agent 卸载
cd /d "%~dp0"

echo ============================================================
echo   Maya Agent 卸载（优先 mayapy，无需系统 Python）
echo ============================================================
echo.
echo 将移除:
echo   - userSetup / userSetup.mel 挂钩
echo   - modules\MayaAgent.mod
echo   - Documents\maya\plug-ins\MayaAgent.py
echo   - 工具架偏好 shelf_MayaAgent.mel
echo   - 目录联接 Documents\maya\版本\MayaAgent
echo.

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
if not defined PYEXE where py >nul 2>&1 && set "PYEXE=py -3"

if not defined PYEXE (
  echo [错误] 未找到 mayapy 或系统 Python。
  echo   请设置 MAYA_AGENT_MAYAPY_ROOTS，或手动运行:
  echo   mayapy scripts\install_engine.py --uninstall
  pause
  exit /b 1
)

echo 使用: %PYEXE%
"%PYEXE%" "%CD%\scripts\install_engine.py" --project-root "%CD%" --uninstall
echo.
echo 完成。请重启 Maya。
echo.
echo 若 Maya 当前正在运行，可在 Script Editor 再执行即时清理:
echo   import maya_agent
echo   maya_agent.plugin.menu.uninstall_ui()
echo.
pause
endlocal
exit /b 0
