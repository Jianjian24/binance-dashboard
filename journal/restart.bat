@echo off
cd /d "%~dp0"
call "%~dp0stop.bat"
timeout /t 1 >nul
call "%~dp0start.bat"
