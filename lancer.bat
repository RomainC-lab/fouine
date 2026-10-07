@echo off
setlocal
cd /d "%~dp0"
title Fouine

if not exist ".venv\Scripts\python.exe" (
  echo Fouine n'est pas encore installe : lancez d'abord installer.bat.
  echo.
  pause
  exit /b 1
)

".venv\Scripts\python.exe" -m fouine %*
if errorlevel 1 (
  echo.
  echo Fouine s'est arrete sur une erreur. Le message ci-dessus dit pourquoi.
  pause
)
