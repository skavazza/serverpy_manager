@echo off
setlocal
cd /d "%~dp0"
echo Verificando ambiente Windows

:: Verifica se o Python esta instalado
set PY=python
python --version >nul 2>&1
if errorlevel 1 (
    py -3 --version >nul 2>&1
    if errorlevel 1 (
        echo Erro: Python nao encontrado. Por favor, instale o Python 3.10 ou superior.
        pause
        exit /b 1
    )
    set PY=py -3
)

:: Recria o venv se foi criado por outro Python (ex: MSYS) e nao tem Scripts
if exist venv if not exist venv\Scripts\activate.bat (
    echo Ambiente virtual invalido. Recriando
    rmdir /s /q venv
)

:: Cria ambiente virtual se nao existir
if not exist venv (
    echo Criando ambiente virtual venv
    %PY% -m venv venv
    if errorlevel 1 (
        echo Erro ao criar o ambiente virtual.
        pause
        exit /b 1
    )
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

:: Inicia o aplicativo sem console (os logs ficam na janela de logs do app)
echo Iniciando ServerPy HTTP Manager
start "" "%CD%\venv\Scripts\pythonw.exe" src\main.py
exit /b 0
