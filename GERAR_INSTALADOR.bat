@echo off
rem Got It! - gera o instalador. De dois cliques neste arquivo.
title Got It! - gerando o instalador
cd /d "%~dp0"
powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0build\build.ps1"
echo.
pause
