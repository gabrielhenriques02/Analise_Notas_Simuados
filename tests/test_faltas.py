"""Analise e relatorio de faltas."""

from __future__ import annotations

import pymupdf
import pytest
from sqlalchemy import select

from app.analytics.faltas import panorama
from app.charts.svg import _escala_do_eixo
from app.db import Sessao
from app.models import Falta, Fase, Materia, Prova
from app.reports import faltas as relatorio_faltas
from tests.conftest import requer_planilha


@pytest.fixture(scope="module")
def s():
    sessao = Sessao()
    yield sessao
    sessao.rollback()
    sessao.close()


# ── eixo dos gráficos ───────────────────────────────────────────────────────────

@pytest.mark.parametrize(
    "maximo, esperado",
    [
        (40.0, [0.0, 10.0, 20.0, 30.0, 40.0, 50.0]),
        (17.5, [0.0, 5.0, 10.0, 15.0, 20.0]),
        (3.0, [0.0, 1.0, 2.0, 3.0, 4.0]),
    ],
)
def test_eixo_usa_numeros_redondos(maximo, esperado):
    """Uma marca de 47% não ajuda ninguém a ler, e um teto de 80% para um máximo
    de 40% espreme as colunas à metade da altura."""
    teto, passo = _escala_do_eixo(maximo)
    marcas = [round(passo * i, 4) for i in range(int(round(teto / passo)) + 1)]
    assert marcas == esperado
    assert teto >= maximo


def test_eixo_aguenta_valores_degenerados():
    for valor in (0.0, -5.0):
        teto, passo = _escala_do_eixo(valor)
        assert teto > 0 and passo > 0


# ── panorama ────────────────────────────────────────────────────────────────────

@requer_planilha
def test_panorama_conta_por_ciclo(s):
    p = panorama(s, Materia.QUIMICA, Fase.SEGUNDA)
    assert p.ciclos == [1, 2, 3, 4, 5]
    assert p.turma == 40
    assert p.por_ciclo == {1: 3, 2: 6, 3: 7, 4: 16, 5: 16}
    assert p.total == 48


@requer_planilha
def test_grupos_de_acompanhamento_nao_se_sobrepoem(s):
    p = panorama(s, Materia.QUIMICA, Fase.SEGUNDA)
    p1 = {a.aluno_id for a in p.prioridade_1}
    p2 = {a.aluno_id for a in p.prioridade_2}
    integral = {a.aluno_id for a in p.presenca_integral}

    assert not p1 & p2                      # ou faltou nos dois, ou em um
    assert not (p1 | p2) & integral         # quem tem presença integral não entra
    assert len(integral) + len({a.aluno_id for a in p.alunos if a.total}) == p.turma


@requer_planilha
def test_distribuicao_soma_a_turma(s):
    p = panorama(s, Materia.QUIMICA, Fase.SEGUNDA)
    assert sum(q for _, q in p.distribuicao) == p.turma


@requer_planilha
def test_falta_descartada_sai_da_conta(s):
    """Quem a coordenação marcou como "fez a prova" não conta como ausência."""
    prova = s.scalar(
        select(Prova).where(
            Prova.ciclo == 5, Prova.fase == Fase.SEGUNDA, Prova.materia == Materia.QUIMICA
        )
    )
    antes = panorama(s, Materia.QUIMICA, Fase.SEGUNDA)

    alvo = s.scalars(select(Falta).where(Falta.prova_id == prova.id)).first()
    alvo.confirmada = False
    s.flush()

    depois = panorama(s, Materia.QUIMICA, Fase.SEGUNDA)
    assert depois.por_ciclo[5] == antes.por_ciclo[5] - 1
    assert depois.pendentes == antes.pendentes - 1

    alvo.confirmada = None
    s.flush()


@requer_planilha
def test_salto_entre_os_periodos(s):
    p = panorama(s, Materia.QUIMICA, Fase.SEGUNDA)
    assert round(p.media_anterior, 1) == 5.3     # ciclos 1 a 3
    assert round(p.media_recente, 1) == 16.0     # ciclos 4 e 5
    assert round(p.salto) == 200


# ── PDF ─────────────────────────────────────────────────────────────────────────

@requer_planilha
def test_pdf_de_faltas(s):
    dados = relatorio_faltas.gerar(
        relatorio_faltas.montar(s, Materia.QUIMICA, Fase.SEGUNDA)
    )
    with pymupdf.open(stream=dados, filetype="pdf") as doc:
        assert doc.page_count == 3
        for pagina in doc:
            assert round(pagina.rect.width) == 842
        texto = "".join(p.get_text() for p in doc)

    # template B: separador "|", classificação de uso interno
    assert "USO INTERNO — DIREÇÃO" in texto
    assert "Turma ITA 2026   |   Ciclos 1 a 5" in texto
    assert "PRIORIDADE 1" in texto and "PRIORIDADE 2" in texto
    assert "PRESENÇA INTEGRAL" in texto


@requer_planilha
def test_pdf_avisa_que_os_numeros_sao_provisorios(s):
    """Enquanto houver ausência sem revisão, o PDF precisa dizer isso — senão alguém
    trata como definitivo um número que ainda vai mudar."""
    dados = relatorio_faltas.gerar(
        relatorio_faltas.montar(s, Materia.QUIMICA, Fase.SEGUNDA)
    )
    with pymupdf.open(stream=dados, filetype="pdf") as doc:
        assert "aguardando revisão" in doc[0].get_text()
        assert "provisórios" in doc[0].get_text()


@requer_planilha
def test_nomes_longos_aparecem_inteiros(s):
    """Regressão: a tabela cortava em 30 caracteres e produzia
    "Joao Vitor Matteoli Delfino Sa"."""
    dados = relatorio_faltas.gerar(
        relatorio_faltas.montar(s, Materia.QUIMICA, Fase.SEGUNDA)
    )
    with pymupdf.open(stream=dados, filetype="pdf") as doc:
        texto = doc[1].get_text()
    assert "Joao Vitor Matteoli Delfino Santana Chaves" in texto
    assert "Guilherme Gomes Barauna do Couto" in texto


@requer_planilha
def test_texto_da_coordenacao_entra_no_pdf(s):
    montado = relatorio_faltas.montar(
        s, Materia.QUIMICA, Fase.SEGUNDA,
        {"IMPACTO": "A aplicação na segunda de manhã conflita com a escola regular."},
    )
    with pymupdf.open(stream=relatorio_faltas.gerar(montado), filetype="pdf") as doc:
        assert "conflita com a escola regular" in doc[2].get_text()
