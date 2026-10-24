@echo off
setlocal
title FindPort - Gerenciador de Portas e Firewall (Windows)

:: Verifica se a sessao atual ja possui privilegios de Administrador
net session >nul 2>&1
if %errorlevel% equ 0 (
    goto :executar
) else (
    echo ================================================================
    echo   FindPort: Solicitando privilegios de Administrador...
    echo ================================================================
    powershell -NoProfile -ExecutionPolicy Bypass -Command "Start-Process powershell -Verb RunAs -ArgumentList '-NoProfile -ExecutionPolicy Bypass -File \"\"%~dp0find_ports.ps1\"\"'"
    exit /b
)

:executar
cd /d "%~dp0"
powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0find_ports.ps1"
if %errorlevel% neq 0 (
    echo.
    echo Ocorreu um erro durante a execucao.
    pause
)
