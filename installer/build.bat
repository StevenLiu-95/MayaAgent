@echo off
chcp 65001 >nul
setlocal EnableExtensions EnableDelayedExpansion
cd /d "%~dp0"

title Build Maya Agent Setup
echo ============================================================
echo   Build MayaAgent-Setup.exe  (Inno Setup)
echo ============================================================
echo.

set "SKIP_CACHE=0"
for %%A in (%*) do (
  if /I "%%~A"=="--skip-cache" set "SKIP_CACHE=1"
  if /I "%%~A"=="skip-cache" set "SKIP_CACHE=1"
)

REM ---- Locate ISCC ----
set "ISCC="
if exist "%LocalAppData%\Programs\Inno Setup 6\ISCC.exe" set "ISCC=%LocalAppData%\Programs\Inno Setup 6\ISCC.exe"
if not defined ISCC if exist "%ProgramFiles(x86)%\Inno Setup 6\ISCC.exe" set "ISCC=%ProgramFiles(x86)%\Inno Setup 6\ISCC.exe"
if not defined ISCC if exist "%ProgramFiles%\Inno Setup 6\ISCC.exe" set "ISCC=%ProgramFiles%\Inno Setup 6\ISCC.exe"
if not defined ISCC (
  where ISCC >nul 2>&1 && for /f "delims=" %%P in ('where ISCC') do set "ISCC=%%P"
)

if not defined ISCC (
  echo [错误] 未找到 Inno Setup 6 的 ISCC.exe
  echo   请安装: https://jrsoftware.org/isdl.php
  echo   或把 ISCC 加入 PATH。
  exit /b 1
)
echo ISCC: %ISCC%

REM ---- Sync VERSION → iss / pyproject / docs ----
where python >nul 2>&1
if not errorlevel 1 (
  echo [版本] sync_version.py
  python "%~dp0..\scripts\sync_version.py"
) else (
  echo [警告] 无系统 Python，跳过 sync_version；请确认 installer\MayaAgent.iss 中 MyAppVersion 正确
)

REM ---- Optional vendor_cache ----
if not exist "%~dp0..\vendor_cache" mkdir "%~dp0..\vendor_cache"
if "!SKIP_CACHE!"=="1" (
  echo [跳过] 不构建 vendor_cache
  if not exist "%~dp0..\vendor_cache\README.txt" (
    echo Offline vendor_cache not bundled.>"%~dp0..\vendor_cache\README.txt"
  )
) else (
  if not exist "%~dp0..\vendor_cache\MANIFEST.txt" (
    echo [构建] vendor_cache …
    where python >nul 2>&1
    if errorlevel 1 (
      echo [警告] 无系统 Python，跳过 vendor_cache。安装包将依赖用户 mayapy 在线装依赖。
      echo Offline vendor_cache not bundled.>"%~dp0..\vendor_cache\README.txt"
    ) else (
      python "%~dp0..\scripts\build_vendor_cache.py"
      if errorlevel 1 (
        echo [警告] vendor_cache 构建有失败，仍继续打包。
      )
    )
  ) else (
    echo [跳过] 已存在 vendor_cache\MANIFEST.txt （删除后可重建）
  )
)

if not exist "%~dp0..\dist" mkdir "%~dp0..\dist"

echo [编译] MayaAgent.iss …
"%ISCC%" "%~dp0MayaAgent.iss"
if errorlevel 1 (
  echo [失败] ISCC 编译失败
  exit /b 1
)

echo.
echo [成功] 输出目录: %~dp0..\dist\
dir /b "%~dp0..\dist\MayaAgent-Setup-*.exe" 2>nul
echo.
exit /b 0
