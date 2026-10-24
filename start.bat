@echo off
setlocal
cd /d "%~dp0"
echo Verificando ambiente Windows

if exist venv goto validate_env
set PY=python
python -c "import sys; sys.exit(sys.version_info < (3, 10))" >nul 2>&1
if errorlevel 1 (
    py -3 -c "import sys; sys.exit(sys.version_info < (3, 10))" >nul 2>&1
    if errorlevel 1 (
        echo Erro: instale Python 3.10 ou superior.
        exit /b 1
    )
    set PY=py -3
)
echo Criando ambiente virtual venv
%PY% -m venv venv
if errorlevel 1 goto failed

:validate_env
if not exist "venv\Scripts\python.exe" (
    echo Erro: venv incompativel. Preserve ou renomeie a pasta e crie um ambiente Windows.
    exit /b 1
)
"venv\Scripts\python.exe" -c "import sys; sys.exit(sys.version_info < (3, 10))"
if errorlevel 1 goto failed
if "%~1"=="--check" (
    "venv\Scripts\python.exe" setup_env.py --check
    exit /b
)
"venv\Scripts\python.exe" setup_env.py
if errorlevel 1 goto failed
if not exist "venv\Scripts\pythonw.exe" (
    echo Erro: pythonw.exe nao encontrado no ambiente virtual.
    exit /b 1
)
set "PYTHONPATH=%CD%;%PYTHONPATH%"
echo Iniciando ServerPy HTTP Manager
start "" "%CD%\venv\Scripts\pythonw.exe" "%CD%\src\main.py"
exit /b %errorlevel%

:failed
echo Erro ao preparar o ambiente. O aplicativo nao foi iniciado.
exit /b 1
