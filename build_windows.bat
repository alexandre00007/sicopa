@echo off
setlocal
cd /d %~dp0

set "TRIAL_DAYS=%~1"
if not defined TRIAL_DAYS (
    set /p "TRIAL_DAYS=Durée de la version d'essai en jours [30] : "
)
if not defined TRIAL_DAYS set "TRIAL_DAYS=30"

py -m pip install -r requirements-build.txt
if errorlevel 1 exit /b 1

py tools\generate_trial_config.py --days %TRIAL_DAYS%
if errorlevel 1 exit /b 1

rem L’icône EXE est définie dans sicorpa.spec
py -m PyInstaller --noconfirm --clean sicorpa.spec
set "BUILD_RESULT=%ERRORLEVEL%"
if exist controle_paie\_trial_build.py del /q controle_paie\_trial_build.py
if not "%BUILD_RESULT%"=="0" exit /b %BUILD_RESULT%

echo.
echo Exécutable d'essai créé : dist\SICORPA.exe (%TRIAL_DAYS% jours)
endlocal
