"""Configuracao lida do ambiente, com valores padrao para desenvolvimento local."""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path

RAIZ = Path(__file__).resolve().parent.parent


def _ler_env() -> None:
    """Carrega o .env sem depender de biblioteca externa."""
    arquivo = RAIZ / ".env"
    if not arquivo.exists():
        return
    for linha in arquivo.read_text(encoding="utf-8").splitlines():
        linha = linha.strip()
        if not linha or linha.startswith("#") or "=" not in linha:
            continue
        chave, _, valor = linha.partition("=")
        os.environ.setdefault(chave.strip(), valor.strip())


_ler_env()


def _caminho(chave: str, padrao: str) -> Path:
    bruto = Path(os.environ.get(chave, padrao))
    return bruto if bruto.is_absolute() else RAIZ / bruto


def _decimal(chave: str, padrao: float) -> float:
    try:
        return float(os.environ[chave])
    except (KeyError, ValueError):
        return padrao


@dataclass(frozen=True)
class Config:
    # Ambiente
    ambiente: str = os.environ.get("ENV", "development")
    chave_secreta: str = os.environ.get("SECRET_KEY", "")

    # Banco
    url_banco: str = os.environ.get("DATABASE_URL", "sqlite:///data/app.db")

    # Pastas de trabalho (fora do versionamento)
    dir_dados: Path = field(default_factory=lambda: _caminho("DATA_DIR", "data"))
    dir_uploads: Path = field(default_factory=lambda: _caminho("UPLOAD_DIR", "data/uploads"))
    dir_provas: Path = field(default_factory=lambda: _caminho("PROVAS_DIR", "data/provas"))
    dir_cache_questoes: Path = field(
        default_factory=lambda: _caminho("CACHE_QUESTOES_DIR", "data/cache_questoes")
    )
    dir_saida: Path = field(default_factory=lambda: _caminho("SAIDA_DIR", "data/saida"))

    # Pastas de origem
    dir_planilha: Path = field(default_factory=lambda: _caminho("PLANILHA_DIR", "planilha_dados"))
    dir_relatorios_referencia: Path = field(
        default_factory=lambda: _caminho("RELATORIOS_REFERENCIA_DIR", "exemplos_relatorios")
    )
    dir_provas_origem: Path = field(
        default_factory=lambda: _caminho("PROVAS_ORIGEM_DIR", "exemplos_pdf_provas")
    )

    # Regras de negocio (ver CLAUDE.md)
    corte_materia: float = field(default_factory=lambda: _decimal("CORTE_MATERIA", 4.0))
    corte_geral: float = field(default_factory=lambda: _decimal("CORTE_GERAL", 5.0))
    corte_ita: float = field(default_factory=lambda: _decimal("CORTE_ITA", 5.83))
    base_ranking_poliedro: int = field(
        default_factory=lambda: int(_decimal("BASE_RANKING_POLIEDRO", 850))
    )

    @property
    def desenvolvimento(self) -> bool:
        return self.ambiente != "production"

    def preparar_pastas(self) -> None:
        for pasta in (
            self.dir_dados,
            self.dir_uploads,
            self.dir_provas,
            self.dir_cache_questoes,
            self.dir_saida,
        ):
            pasta.mkdir(parents=True, exist_ok=True)


config = Config()
