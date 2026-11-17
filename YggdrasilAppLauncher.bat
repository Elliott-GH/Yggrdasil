@echo off
setlocal
set "VDIR=%~dp0"
set "PYTHONPATH="
set "PYDIR=C:\AntiGravityFiles\MasterAgent\.venv\Scripts"
if exist "%VDIR%.venv\Scripts\python.exe" set "PYDIR=%VDIR%.venv\Scripts"
if not exist "%PYDIR%\python.exe" goto :no_python
if not "%~1"=="" goto :cli
start "YggdrasilStudioV5" "%PYDIR%\pythonw.exe" "%VDIR%Yggdrasil.pyw"
exit /b 0
:cli
"%PYDIR%\python.exe" "%VDIR%app-0.5.0\YggdrasilStudio.pyw" %*
exit /b %ERRORLEVEL%
:no_python
echo [Yggdrasil] No Python environment found.
echo Expected: %VDIR%.venv\Scripts\python.exe
echo       or: C:\AntiGravityFiles\MasterAgent\.venv\Scripts\python.exe
pause
exit /b 1
