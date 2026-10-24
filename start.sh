#!/bin/bash

# Define o diretório atual do script como o diretório de trabalho
cd "$(dirname "$0")"

echo "Verificando ambiente..."

# Verifica se o diretório do ambiente virtual existe
if [ ! -d "venv" ]; then
    echo "Criando ambiente virtual (venv)..."
    python3 -m venv venv
    if [ $? -ne 0 ]; then
        echo "Erro ao criar o ambiente virtual. Certifique-se de ter o pacote venv instalado (ex: sudo apt install python3-venv)."
        exit 1
    fi
fi

# Ativa o ambiente virtual
source venv/bin/activate

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
./venv/bin/python3 src/main.py
