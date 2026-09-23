#!/usr/bin/env python
"""Cria a primeira conta de coordenacao.

    .venv/bin/python scripts/criar_admin.py coordenacao@madan.com.br "Coordenação"
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app import auth
from app.db import criar_tabelas, sessao
from app.models import Papel


def main(argv: list[str]) -> int:
    if len(argv) < 3:
        print(__doc__)
        return 1
    email, nome = argv[1], argv[2]
    senha = argv[3] if len(argv) > 3 else None

    criar_tabelas()
    with sessao() as s:
        try:
            usuario, inicial = auth.criar_usuario(
                s, email=email, nome=nome, papel=Papel.ADMIN, senha=senha
            )
        except ValueError as erro:
            print(f"  {erro}")
            return 1

    print(f"\n  Conta criada: {usuario.email}")
    print(f"  Senha inicial: {inicial}")
    print("\n  Troque a senha no primeiro acesso.\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
