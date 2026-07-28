@echo off
rem NeuRAG — click-and-go installer (Windows). Double-click me.
rem Runs the unified Gray Matter installer via install.ps1 (add --no-gm for standalone).
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
