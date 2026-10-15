@echo off
setlocal
cd /d "%~dp0"
echo MayaAgent Local Runtime installer
echo Weights are NOT downloaded here — use MayaAgent UI after install.
echo.
python scripts\install_local_runtime.py %*
set ERR=%ERRORLEVEL%
echo.
if %ERR% NEQ 0 (
  echo Install failed with code %ERR%
  pause
  exit /b %ERR%
)
echo Install finished.
pause
exit /b 0
