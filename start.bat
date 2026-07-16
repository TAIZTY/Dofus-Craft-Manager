@echo off
setlocal
cd /d "%~dp0"
title Dofus Craft Manager - Salar V3.4
set "PYTHON_CMD="
where py >nul 2>&1 && set "PYTHON_CMD=py -3"
if not defined PYTHON_CMD where python >nul 2>&1 && set "PYTHON_CMD=python"
if not defined PYTHON_CMD (
  echo Python 3 est introuvable.
  echo Installe Python depuis https://www.python.org/downloads/windows/
  echo Coche "Add python.exe to PATH" pendant l'installation.
  pause
  exit /b 1
)
start "" powershell -NoProfile -WindowStyle Hidden -Command "Start-Sleep -Seconds 2; Start-Process 'http://127.0.0.1:8765'"
%PYTHON_CMD% server.py
if errorlevel 1 (
  echo.
  echo Le serveur s'est arrete avec une erreur.
  pause
)
endlocal
