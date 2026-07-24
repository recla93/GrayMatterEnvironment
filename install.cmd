@echo off
rem NeuRAG - click-and-go installer (Windows). Double-click me.
rem Installs NeuRAG standalone (optionally with Gray Matter).
powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0install.ps1" %*
echo.
pause
