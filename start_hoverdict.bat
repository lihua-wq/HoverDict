@echo off
rem Start HoverDict in the background.
rem - if it is already running, this only asks the running instance to show the wordbook;
rem - going through cmd.exe (a signed Microsoft binary) avoids the SmartScreen prompt
rem   that an unsigned pythonw.exe launcher would trigger.
setlocal
set "BASE=%~dp0"
if not exist "%BASE%data" mkdir "%BASE%data"

if exist "%BASE%data\show.request" del /q "%BASE%data\show.request" >nul 2>&1
> "%BASE%data\show.request" echo.
ping -n 2 127.0.0.1 >nul
if exist "%BASE%data\show.request" (
    start "" /B "%BASE%.venv\Scripts\pythonw.exe" "%BASE%main.py"
)
