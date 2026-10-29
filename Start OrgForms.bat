@echo off
setlocal
title OrgForms Server
pushd "%~dp0"
if errorlevel 1 (
    echo Could not open the OrgForms folder.
    pause
    exit /b 1
)

if not exist ".venv\Scripts\python.exe" (
    echo OrgForms needs its one-time Windows setup before it can start.
    echo Ask the person setting up this computer to follow README.md.
    echo Keep this shortcut with the complete project folder.
    popd
    pause
    exit /b 1
)

".venv\Scripts\python.exe" "start_orgforms.py" %*
set "orgforms_exit_code=%errorlevel%"
popd
if not "%orgforms_exit_code%"=="0" pause
exit /b %orgforms_exit_code%
