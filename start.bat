@echo off
setlocal
cd /d "%~dp0"
echo Verificando ambiente Windows

:: Verifica se o Python esta instalado
python --version >nul 2>&1
if errorlevel 1 (
    echo Erro: Python nao encontrado. Por favor, instale o Python 3.10 ou superior.
    pause
    exit /b
)

:: Cria ambiente virtual se nao existir
if not exist venv (
    echo Criando ambiente virtual venv
    python -m venv venv
)

:: Ativa o ambiente e instala dependencias apenas se necessario
call venv\Scripts\activate
python -c "import PySide6; import psutil" >nul 2>&1
if errorlevel 1 (
    echo Instalando dependencias do requirements.txt
    python -m pip install --upgrade pip
    pip install -r requirements.txt
)

:: Define o PYTHONPATH para encontrar o pacote src
set PYTHONPATH=%CD%;%PYTHONPATH%

:: Inicia o aplicativo
echo Iniciando ServerPy HTTP Manager
python src/main.py

pause
