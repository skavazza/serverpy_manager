#!/bin/bash
set -eu
cd -- "$(dirname -- "$0")"
echo "Verificando ambiente..."

if [ ! -e venv ]; then
    PYTHON_BIN=python3
    command -v python3 >/dev/null 2>&1 || PYTHON_BIN=python
    if ! "$PYTHON_BIN" -c 'import sys; sys.exit(sys.version_info < (3, 10))'; then
        echo "Erro: instale Python 3.10 ou superior." >&2
        exit 1
    fi
    "$PYTHON_BIN" -m venv venv
fi

if [ -x venv/bin/python ]; then
    VENV_PY=venv/bin/python
elif [ -f venv/Scripts/python.exe ]; then
    VENV_PY=venv/Scripts/python.exe
else
    echo "Erro: venv incompativel. Preserve ou renomeie a pasta e crie um ambiente para este sistema." >&2
    exit 1
fi
"$VENV_PY" -c 'import sys; sys.exit(sys.version_info < (3, 10))'
if [ "${1:-}" = "--check" ]; then
    exec "$VENV_PY" setup_env.py --check
fi
"$VENV_PY" setup_env.py
export PYTHONPATH="$PWD${PYTHONPATH:+:$PYTHONPATH}"
echo "Iniciando ServerPy HTTP Manager..."
exec "$VENV_PY" src/main.py
