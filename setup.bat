@echo off
rem Create .venv and install dependencies. Requires Python 3.12 on PATH.
setlocal
set "BASE=%~dp0"
pushd "%BASE%" || exit /b 1

set "PYCMD=python"
where py >nul 2>&1 && set "PYCMD=py -3.12"

echo [1/3] creating virtual environment...
%PYCMD% -m venv "%BASE%.venv"
if errorlevel 1 (
    echo.
    echo Failed. Install Python 3.12 from https://www.python.org/downloads/ and try again.
    popd & pause & exit /b 1
)

echo [2/3] upgrading pip...
"%BASE%.venv\Scripts\python.exe" -m pip install --upgrade pip

echo [3/3] installing requirements...
"%BASE%.venv\Scripts\python.exe" -m pip install -r "%BASE%requirements.txt"
if errorlevel 1 (
    echo.
    echo Install failed. Check the messages above.
    popd & pause & exit /b 1
)

echo.
echo Done. Now edit data\config.json and set "dict_dir" to the folder with your .mdx files,
echo then run start_hoverdict.bat
popd
pause
