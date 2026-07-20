@echo off
setlocal
cd /d "%~dp0"
title DCM V7 - Serveur prive

set "PYTHON_CMD="
where py >nul 2>&1 && set "PYTHON_CMD=py -3"
if not defined PYTHON_CMD where python >nul 2>&1 && set "PYTHON_CMD=python"

if not defined PYTHON_CMD (
    echo.
    echo Python 3 est introuvable.
    echo Installe Python depuis python.org et coche "Add Python to PATH".
    echo.
    pause
    exit /b 1
)

echo.
echo Demarrage du serveur DCM V7...
echo.
%PYTHON_CMD% server.py

if errorlevel 1 (
    echo.
    echo Le serveur s'est arrete avec une erreur.
)

pause
endlocal
