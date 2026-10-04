@echo off
setlocal
cd /d "%~dp0"

echo ============================================
echo   CodeTime - building EXE with PyInstaller
echo ============================================
echo.

rem ------------------------------------------------
rem Find a working Python (the Microsoft Store stub
rem "python.exe" fails on --version, so we test it).
rem ------------------------------------------------
set "PYEXE="
python --version >nul 2>nul
if not errorlevel 1 set "PYEXE=python"
if not defined PYEXE (
    py --version >nul 2>nul
    if not errorlevel 1 set "PYEXE=py"
)
if not defined PYEXE goto :nopython

echo Found Python:
%PYEXE% --version
echo.

echo [1/4] Installing dependencies (pynput, pystray, pillow, pywebview, pyinstaller)...
%PYEXE% -m pip install -r requirements.txt
if errorlevel 1 goto :fail

echo.
echo [2/4] Generating icon.ico ...
%PYEXE% make_icon.py
if errorlevel 1 goto :fail

echo.
echo [3/4] Cleaning old build files ...
if exist build rmdir /s /q build
if exist dist rmdir /s /q dist
if exist CodeTime.spec del /q CodeTime.spec

echo.
echo [4/4] Building EXE - this may take a few minutes ...
%PYEXE% -m PyInstaller --onefile --noconsole --name CodeTime --icon=icon.ico --add-data "dashboard.html;." --hidden-import pynput.keyboard --hidden-import pynput.keyboard._win32 --hidden-import pynput.mouse --hidden-import pynput.mouse._win32 --hidden-import pystray._win32 --collect-all webview --collect-all pythonnet --collect-all clr_loader --hidden-import webview.platforms.edgechromium --hidden-import webview.platforms.winforms codetime.py
if errorlevel 1 goto :fail

if not exist "dist\CodeTime.exe" goto :fail

echo.
echo ============================================
echo   DONE!
echo.
echo   Your EXE is here:
echo   %~dp0dist\CodeTime.exe
echo.
echo   First launch takes a few seconds (unpack).
echo   A desktop shortcut "CodeTime" is created
echo   automatically. Run it - the app window
echo   opens, tracking runs in the tray.
echo ============================================
echo.
start "" explorer "%~dp0dist"
pause
endlocal
exit /b 0

:nopython
echo.
echo [ERROR] Python not found or not working.
echo.
echo Install Python 3.10+ from https://www.python.org/downloads/
echo and CHECK the box "Add python.exe to PATH" on the first
echo screen of the installer, then run this file again.
echo.
pause
endlocal
exit /b 1

:fail
echo.
echo [ERROR] Build failed - see the messages above.
echo.
echo Common causes:
echo  - no internet connection for pip
echo  - antivirus blocks PyInstaller (add an exclusion)
echo  - Python installed without the "Add to PATH" checkbox
echo.
pause
endlocal
exit /b 1
