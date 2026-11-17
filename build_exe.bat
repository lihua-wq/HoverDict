@echo off
rem Double-click wrapper for build_exe.ps1
setlocal
set "BASE=%~dp0"
powershell -NoProfile -ExecutionPolicy Bypass -File "%BASE%build_exe.ps1"
pause
