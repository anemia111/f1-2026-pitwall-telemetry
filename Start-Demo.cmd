@echo off
cd /d "%~dp0"
powershell.exe -NoLogo -NoProfile -File "%~dp0Start-PitWall.ps1" -Demo %*
pause
