@echo off
rem SnipScout launcher for Windows. Double-click it.
rem First run: installs uv into .uv (only with your consent), prepares Python and the dependencies,
rem then opens SnipScout. Extra arguments are passed to the `snipscout` command (default: ui).
setlocal EnableExtensions
chcp 65001 >nul
cd /d "%~dp0"
set "APPDIR=%~dp0"
set "UVDIR=%APPDIR%.uv"
set "LOG=%APPDIR%snipscout-error.log"
set "ISSUES=https://github.com/datamauriciovaldez/SnipScout/issues"
title SnipScout
type nul > "%LOG%"
echo.
echo   SnipScout
echo.

rem 1) uv: already installed, our private copy, or install it (with consent).
set "UV="
where uv >nul 2>nul && set "UV=uv"
if not defined UV if exist "%UVDIR%\uv.exe" set "UV=%UVDIR%\uv.exe"
if defined UV goto :prepare
echo   SnipScout necesita "uv" para preparar Python la primera vez (unos 30 MB).
echo   SnipScout needs "uv" to set up Python the first time (about 30 MB).
if "%SNIPSCOUT_ASSUME_YES%"=="1" goto :install
choice /c SYN /n /m "  Instalarlo ahora en esta carpeta? / Install it now in this folder? [S/Y = si/yes, N = no] "
if errorlevel 3 goto :declined
:install
powershell -NoProfile -ExecutionPolicy Bypass -Command "$env:UV_UNMANAGED_INSTALL='%UVDIR%'; irm https://github.com/astral-sh/uv/releases/latest/download/uv-installer.ps1 | iex" >>"%LOG%" 2>&1
if not exist "%UVDIR%\uv.exe" goto :failed_uv
set "UV=%UVDIR%\uv.exe"

:prepare
rem 2) Python + dependencies (first run downloads a few hundred MB; later runs are instant).
echo   Preparando SnipScout (la primera vez tarda unos minutos)...
echo   Preparing SnipScout (the first time takes a few minutes)...
"%UV%" sync --project "%APPDIR%." --no-dev --managed-python --python 3.12 >>"%LOG%" 2>&1
if errorlevel 1 goto :failed_sync

rem 3) Run.
if "%~1"=="" (
  "%UV%" run --project "%APPDIR%." --no-dev --no-sync snipscout ui 2>>"%LOG%"
) else (
  "%UV%" run --project "%APPDIR%." --no-dev --no-sync snipscout %* 2>>"%LOG%"
)
if errorlevel 1 goto :failed_run
del "%LOG%" >nul 2>nul
exit /b 0

:declined
echo   Cancelado. / Cancelled.
pause
exit /b 1

:failed_uv
set "WHAT=uv"
goto :failed
:failed_sync
set "WHAT=uv sync"
goto :failed
:failed_run
set "WHAT=snipscout"
:failed
echo.
echo   Algo ha fallado / Something went wrong: %WHAT%
echo   Detalles / Details: %LOG%
echo   Puedes adjuntar ese archivo en / You can attach that file at: %ISSUES%
echo.
pause
exit /b 1
