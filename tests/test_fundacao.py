"""Testes da etapa 1: o ambiente esta de pe e as travas de privacidade funcionam."""

from __future__ import annotations

import subprocess
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app.config import RAIZ, config
from app.main import app


@pytest.fixture(scope="module")
def cliente():
    with TestClient(app) as c:
        yield c


def test_aplicacao_responde(cliente):
    resposta = cliente.get("/saude")
    assert resposta.status_code == 200
    assert resposta.json()["status"] == "ok"


def test_regras_de_negocio_conferem_com_a_coordenacao():
    # Valores decididos com a coordenacao; a planilha usa 4,16 e deve ser ignorada.
    assert config.corte_materia == 4.0
    assert config.corte_geral == 5.0


def test_pastas_de_trabalho_sao_criadas():
    config.preparar_pastas()
    for pasta in (config.dir_uploads, config.dir_provas, config.dir_saida):
        assert pasta.is_dir()


@pytest.mark.parametrize(
    "caminho",
    [
        "data/app.db",
        "planilha_dados/CORREÇÃO SIMULADOS 2026.xlsx",
        "exemplos_relatórios/relatorios_1fase/qualquer.pdf",
        "exemplos_pdf_provas/CICLO 1/prova.pdf",
        "relatorio.xlsx",
    ],
)
def test_gitignore_bloqueia_dado_de_aluno(caminho: str):
    """O repositorio e publico: nenhum arquivo de aluno pode ser versionavel."""
    resultado = subprocess.run(
        ["git", "check-ignore", "-q", caminho],
        cwd=RAIZ,
        capture_output=True,
    )
    assert resultado.returncode == 0, f"{caminho} NAO esta bloqueado pelo .gitignore"


def test_planilha_de_exemplo_e_versionavel():
    """samples/ e a excecao: precisa entrar no git para quem clonar o projeto."""
    resultado = subprocess.run(
        ["git", "check-ignore", "-q", "samples/exemplo.xlsx"],
        cwd=RAIZ,
        capture_output=True,
    )
    assert resultado.returncode != 0, "samples/ nao deveria estar bloqueado"


def test_hook_de_pre_commit_existe_e_e_executavel():
    hook = Path(RAIZ, "scripts/pre-commit")
    assert hook.is_file()
    assert hook.stat().st_mode & 0o111, "o hook precisa ser executavel"


def _hook_bloqueia(caminho_relativo: str, tmp_repo: Path) -> bool:
    """Roda o hook contra um indice que contem o arquivo dado."""
    subprocess.run(["git", "add", "-f", "--", caminho_relativo], cwd=tmp_repo, check=True)
    resultado = subprocess.run(
        [str(RAIZ / "scripts" / "pre-commit")],
        cwd=tmp_repo,
        capture_output=True,
    )
    subprocess.run(["git", "rm", "-q", "--cached", "--", caminho_relativo], cwd=tmp_repo)
    return resultado.returncode != 0


@pytest.fixture
def repo_temporario(tmp_path: Path) -> Path:
    subprocess.run(["git", "init", "-q"], cwd=tmp_path, check=True)
    return tmp_path


@pytest.mark.parametrize(
    "caminho",
    [
        # Regressao: o git escapa nomes acentuados entre aspas. Sem
        # core.quotepath=false o hook deixava passar justamente as pastas
        # deste projeto, que todas tem acento.
        "exemplos_relatórios/relatorios_1fase/Relatório - Ciclo 5.pdf",
        "planilha_dados/CORREÇÃO SIMULADOS 2026.xlsx",
        "data/app.db",
        "exemplos_pdf_provas/CICLO 1/Ciclo 1 - Física.pdf",
        "notas.xlsx",
    ],
)
def test_hook_bloqueia_dado_de_aluno(caminho: str, repo_temporario: Path):
    alvo = repo_temporario / caminho
    alvo.parent.mkdir(parents=True, exist_ok=True)
    alvo.write_text("conteudo", encoding="utf-8")
    assert _hook_bloqueia(caminho, repo_temporario), f"o hook deixou passar {caminho}"


def test_hook_libera_codigo_e_amostras(repo_temporario: Path):
    for caminho in ("app/main.py", "samples/exemplo.xlsx", "README.md"):
        alvo = repo_temporario / caminho
        alvo.parent.mkdir(parents=True, exist_ok=True)
        alvo.write_text("conteudo", encoding="utf-8")
        assert not _hook_bloqueia(caminho, repo_temporario), f"o hook bloqueou {caminho}"
