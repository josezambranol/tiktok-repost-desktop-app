@echo off
title Crear Acceso Directo - TikTok Auto Unrepost
cd /d "%~dp0"
powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0crear_acceso.ps1"
echo.
pause
