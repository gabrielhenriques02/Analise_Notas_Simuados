#!/usr/bin/env bash
# Prepara o ambiente do zero. Nao exige sudo.
set -euo pipefail
raiz="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$raiz"

if [ ! -x .venv/bin/python ]; then
  echo "==> criando o ambiente virtual"
  python3 -m venv --without-pip .venv
fi

if [ ! -x .venv/bin/pip ]; then
  echo "==> instalando o pip (o Python do sistema nao traz ensurepip)"
  curl -sS https://bootstrap.pypa.io/get-pip.py -o /tmp/get-pip.py
  .venv/bin/python /tmp/get-pip.py
fi

echo "==> instalando as dependencias"
.venv/bin/pip install -q -r requirements.txt

[ -f .env ] || { cp .env.example .env; echo "==> .env criado a partir de .env.example"; }

echo "==> pronto. Inicie com: scripts/run.sh"
