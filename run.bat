@echo off
rem Run HoverDict with a console window (useful for seeing errors / logs).
setlocal
set "BASE=%~dp0"
if not exist "%BASE%data" mkdir "%BASE%data"
"%BASE%.venv\Scripts\python.exe" "%BASE%main.py"
pause
