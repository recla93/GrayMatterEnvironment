@echo off
rem Gray Matter (full suite) — click-and-go installer (Windows). Double-click me.
rem The GM repo bundles Neuron + NeuRAG: this installs everything.
powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0install.ps1" %*
echo.
pause
