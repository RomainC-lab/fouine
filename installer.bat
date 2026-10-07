@echo off
setlocal
cd /d "%~dp0"
title Installation de Fouine

set "PY=py -3"
py -3 --version >nul 2>nul
if errorlevel 1 (
  set "PY=python"
  python --version >nul 2>nul
  if errorlevel 1 (
    echo.
    echo Python n'est pas installe sur ce PC.
    echo Installez-le depuis https://www.python.org/downloads/ en cochant
    echo la case "Add python.exe to PATH", puis relancez installer.bat.
    echo.
    pause
    exit /b 1
  )
)

echo Preparation de Fouine (quelques minutes, une seule fois)...
%PY% -m venv .venv
if errorlevel 1 goto erreur
".venv\Scripts\python.exe" -m pip install --upgrade pip
".venv\Scripts\python.exe" -m pip install -r requirements.txt
if errorlevel 1 goto erreur

echo.
echo Installation terminee. Double-cliquez sur lancer.bat pour demarrer Fouine.
echo.
pause
exit /b 0

:erreur
echo.
echo L'installation n'a pas marche. Verifiez la connexion Internet et que Python
echo est en version 3.10 ou plus recente, puis relancez installer.bat.
echo.
pause
exit /b 1
