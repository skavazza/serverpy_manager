#!/bin/bash

# Define o diretório atual do script como o diretório de trabalho
cd "$(dirname "$0")"

echo "Verificando ambiente..."

PYTHON_BIN=python3
command -v python3 >/dev/null 2>&1 || PYTHON_BIN=python

# Recria o venv se estiver quebrado (ex: criado por outro Python)
if [ -d "venv" ]; then
    if [ -x "venv/bin/python3" ]; then VENV_PY="venv/bin/python3"; else VENV_PY="venv/Scripts/python.exe"; fi
    if ! "$VENV_PY" -c "import sys" >/dev/null 2>&1; then
        echo "Ambiente virtual inválido. Recriando..."
        rm -rf venv
    fi
fi

# Verifica se o diretório do ambiente virtual existe
if [ ! -d "venv" ]; then
    echo "Criando ambiente virtual (venv)..."
    "$PYTHON_BIN" -m venv venv
    if [ $? -ne 0 ]; then
        echo "Erro ao criar o ambiente virtual. Certifique-se de ter o pacote venv instalado (ex: sudo apt install python3-venv)."
        exit 1
    fi
fi

# Ativa o ambiente virtual
if [ -f "venv/bin/activate" ]; then
    source venv/bin/activate
else
    source venv/Scripts/activate
fi

# Instala as dependências se o requirements.txt existir
if [ -f "requirements.txt" ]; then
    echo "Instalando ou atualizando dependências do requirements.txt..."
    pip install -r requirements.txt
else
    echo "Aviso: requirements.txt não encontrado."
fi

echo "Iniciando o servidor HTTP Manager (PySide6)..."
# Usar PYTHONPATH para garantir que o pacote 'src' seja encontrado
export PYTHONPATH=$PYTHONPATH:.
python src/main.py
