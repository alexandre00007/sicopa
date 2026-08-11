@echo off
setlocal
cd /d %~dp0
py -m pip install -r requirements-build.txt
if errorlevel 1 exit /b 1
py -m PyInstaller --noconfirm sicorpa.spec
if errorlevel 1 exit /b 1
echo.
echo Exécutable créé : dist\SICORPA.exe
endlocal
