@echo off
cd /d "%~dp0"
echo === Diagnostic Dofus Craft Manager ===
where py
where python
py -3 --version
python --version
netstat -ano | findstr :8765
pause
