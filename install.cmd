@echo off
rem Gray Matter (full suite) — click-and-go installer (Windows). Double-click me.
rem The GM repo bundles Neuron + NeuRAG: this installs everything.
rem
rem   install.cmd            normal install
rem   install.cmd -Force     repair: reinstall the code at the same version
rem   install.cmd -Clear     last resort: wipe the venv and rebuild (implies -Force)
rem                          CODE only — graphs, knowledge.db and bridges are kept
powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0install.ps1" %*
set RC=%ERRORLEVEL%
echo.
pause
rem Propagate the installer's exit code: `pause` alone always returned 0, so a
rem failed install looked successful to anything calling this launcher.
exit /b %RC%
