"""Confere a leitura e a reconciliacao contra a planilha e os relatorios reais."""

from __future__ import annotations

import statistics

import pytest

from app.ingest.normalize import Reconciliador, normalizar_nome, normalizar_rm
from tests.conftest import requer_planilha


# ── normalizacao ────────────────────────────────────────────────────────────────

@pytest.mark.parametrize(
    "bruto, esperado",
    [
        ("ÍTALO ROSA DOS REIS", "ITALO ROSA DOS REIS"),
        ("Italo Rosa dos Reis", "ITALO ROSA DOS REIS"),
        ("JOÃO PEDRO", "JOAO PEDRO"),
        ("AUGUSTO FABRETE BRAGANÇA", "AUGUSTO FABRETE BRAGANCA"),
        ("  MURILO   COSER  ROCHA ", "MURILO COSER ROCHA"),
        ("GUILHERME GOMES BARAÚNA DO COUTO", "GUILHERME GOMES BARAUNA DO COUTO"),
        (None, ""),
    ],
)
def test_normalizar_nome(bruto, esperado):
    assert normalizar_nome(bruto) == esperado


@pytest.mark.parametrize(
    "bruto, esperado",
    [("\t0383083", "383083"), (383083, "383083"), ("9093281", "9093281"), (None, None), ("", None)],
)
def test_normalizar_rm(bruto, esperado):
    """O RM vem ora como numero, ora como string com TAB e zeros a esquerda."""
    assert normalizar_rm(bruto) == esperado


def test_apelidos_conhecidos_resolvem():
    roster = ["LUCAS EMANUEL GONCALVES GUIMARAES", "MIGUEL GUISAN ABREU LIMA"]
    rec = Reconciliador(roster)
    assert rec.resolver("LUCAS EMANUEL GONÇAVELS GUIMARÃES") == "LUCAS EMANUEL GONCALVES GUIMARAES"
    assert rec.resolver("Miguel Guisan Abreu de Lima") == "MIGUEL GUISAN ABREU LIMA"
    assert rec.resolver("PESSOA QUE NAO EXISTE") is None


# ── leitura da planilha real ────────────────────────────────────────────────────

@requer_planilha
def test_roster_e_lancamentos(planilha):
    assert len(planilha.roster) == 40
    assert len(planilha.lancamentos) > 1700


@requer_planilha
def test_linhas_fantasma_sao_descartadas(planilha):
    """As linhas 583-667 da 2ª fase tem formula viva mas nao tem nome."""
    assert all(l.nome_bruto.strip() for l in planilha.lancamentos)


@requer_planilha
def test_normalizacao_colapsa_as_grafias(planilha):
    """89 grafias na planilha viram 43 nomes distintos so com a normalizacao."""
    assert len(planilha.ocorrencias_de_nomes()) == 43


@requer_planilha
def test_reconciliacao_identifica_os_casos_reais(planilha):
    rec = Reconciliador(planilha.roster).reconciliar(planilha.ocorrencias_de_nomes())

    assert rec.total_reconhecidos == 39
    por_nome = {p.nome_normalizado: p for p in rec.pendencias}

    # Augusto aparece em toda a planilha e nos relatorios como um dos 8 destaques,
    # mas esta ausente da aba ALUNOS MADAN 2026 — o roster e que esta incompleto.
    assert por_nome["AUGUSTO FABRETE BRAGANCA"].tipo == "provavel_aluno_novo"
    # Arthur tem um unico lancamento: nao da para tratar como aluno da turma.
    assert por_nome["ARTHUR DE CARVALHO FARIA DAMASCENO"].tipo == "registro_avulso"
    # Matriculado sem nenhum lancamento.
    assert rec.sem_dados == ["VITOR HOTH FRANCESE"]


@requer_planilha
def test_niveis_normalizam_o_vocabulario(planilha):
    """A planilha usa MÉDIO na 2ª fase e MÉDIA na 1ª para o mesmo nivel."""
    valores = {n for mapa in planilha.niveis.values() for n in mapa.values()}
    assert valores <= {"FÁCIL", "MÉDIO", "DIFÍCIL"}
    assert "MÉDIA" not in valores


# ── conferencia contra os relatorios de referencia ──────────────────────────────

def _presentes(planilha, ciclo: int, materia: str):
    """Presenca na 1ª fase: quem pontuou em Mat+Fis+Qui. Nao ha coluna de falta."""
    saida = []
    for linha in planilha.lancamentos:
        if not (linha.fase == "1ª FASE" and linha.ciclo == ciclo and linha.materia == materia):
            continue
        do_aluno = [
            x for x in planilha.lancamentos
            if x.fase == "1ª FASE" and x.ciclo == ciclo
            and x.nome_normalizado == linha.nome_normalizado
            and x.materia in ("MATEMÁTICA", "FÍSICA", "QUÍMICA")
        ]
        if sum(sum(x.notas.values()) for x in do_aluno) > 0:
            saida.append(linha)
    return saida


def _nota(linha) -> float:
    return sum(linha.notas.values()) / 12 * 10


@requer_planilha
def test_ciclo5_matematica_bate_com_o_relatorio(planilha):
    """Relatório - Ciclo 5 - 1ª Fase - Matematica.pdf, página 1."""
    notas = sorted((_nota(l) for l in _presentes(planilha, 5, "MATEMÁTICA")), reverse=True)

    assert len(notas) == 30                                    # "30 alunos avaliados de 39"
    assert round(statistics.mean(notas), 2) == 5.61            # MÉDIA DA TURMA
    assert sum(1 for n in notas if n > 4.0) == 26              # ACIMA DO CORTE 26/30
    assert round(statistics.mean(notas[:5]), 2) == 8.67        # MÉDIA DOS 5 MELHORES
    assert round(notas[0], 2) == 10.00                         # maior nota


@requer_planilha
def test_variacao_entre_ciclos_bate_com_o_relatorio(planilha):
    """VARIAÇÃO VS. CICLO 4 = +0,90, com o Ciclo 4 em 4,71."""
    c4 = statistics.mean(_nota(l) for l in _presentes(planilha, 4, "MATEMÁTICA"))
    c5 = statistics.mean(_nota(l) for l in _presentes(planilha, 5, "MATEMÁTICA"))

    assert round(c4, 2) == 4.71
    assert round(c5 - c4, 2) == 0.90


@requer_planilha
def test_ciclo5_fisica_bate_com_o_relatorio(planilha):
    """Relatório - Ciclo 5 - 1ª Fase - Fisica.pdf: média 3,78 (+0,13 vs. Ciclo 4)."""
    c4 = statistics.mean(_nota(l) for l in _presentes(planilha, 4, "FÍSICA"))
    c5 = statistics.mean(_nota(l) for l in _presentes(planilha, 5, "FÍSICA"))

    assert round(c5, 2) == 3.78
    assert round(c5 - c4, 2) == 0.13
