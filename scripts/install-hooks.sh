#!/usr/bin/env bash
# Instala os hooks de git do projeto em .git/hooks/
set -euo pipefail
raiz="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
[ -d "$raiz/.git" ] || { echo "Nao e um repositorio git: $raiz" >&2; exit 1; }
install -m 755 "$raiz/scripts/pre-commit" "$raiz/.git/hooks/pre-commit"
echo "Hook pre-commit instalado — commits com dados de aluno serao recusados."
