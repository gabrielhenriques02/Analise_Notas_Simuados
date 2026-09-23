"""Relatorios de potenciais de aprovacao e unificado."""

from __future__ import annotations

import pymupdf
import pytest

from app.analytics.potenciais import cortes_do_grupo, destaques
from app.analytics.unificado import faixa_da_posicao, montar as montar_unificado
from app.db import Sessao
from app.reports import potenciais as relatorio_potenciais
from app.reports import unificado as relatorio_unificado
from tests.conftest import requer_planilha


@pytest.fixture(scope="module")
def s():
    sessao = Sessao()
    yield sessao
    sessao.rollback()
    sessao.close()


# ── potenciais ──────────────────────────────────────────────────────────────────

@requer_planilha
def test_seleciona_os_mesmos_oito_do_relatorio(s):
    """O critério é a média geral da 1ª fase; o resultado bate com a seleção
    que a coordenação fez à mão no relatório de referência."""
    nomes = {d.nome for d in destaques(s)}
    esperados = {
        "MURILO COSER ROCHA", "GUILHERME MACHADO MESQUITA", "LIVIA DA SILVA WAGMAKER",
        "LUCAS LIMA DALLAPICULLA", "HIAGO PISSINATI GALON", "ITALO ROSA DOS REIS",
        "LUCAS EMANUEL GONCALVES GUIMARAES", "AUGUSTO FABRETE BRAGANCA",
    }
    assert nomes == esperados


@requer_planilha
def test_dossie_do_murilo(s):
    murilo = next(d for d in destaques(s) if d.nome.startswith("MURILO"))
    assert murilo.aprovacoes == 5 and murilo.realizados == 5
    assert round(murilo.regularidade, 2) == 0.73
    assert round(murilo.faceis_por_prova, 1) == 2.6
    # "Química: frente F2 (50%)" no relatório de referência
    assert murilo.travamento.rotulo == "QUÍ · F2"
    assert round(murilo.travamento.aproveitamento) == 50


@requer_planilha
def test_frente_com_poucas_questoes_nao_vira_diagnostico(s):
    for dossie in destaques(s):
        assert all(f.total >= 4 for f in dossie.frentes)


@requer_planilha
def test_cortes_do_grupo_somam_por_disciplina(s):
    cortes = cortes_do_grupo(destaques(s))
    assert cortes["QUÍMICA"] >= cortes["MATEMÁTICA"]
    assert sum(cortes.values()) == sum(
        sum(d.cortes.values()) for d in destaques(s)
    )


@requer_planilha
def test_pdf_de_potenciais(s):
    montado = relatorio_potenciais.montar(s)
    dados = relatorio_potenciais.gerar(montado)
    with pymupdf.open(stream=dados, filetype="pdf") as doc:
        assert doc.page_count == 9          # visão do grupo + 8 alunos
        primeira = doc[0].get_text()
        segunda = doc[1].get_text()

    assert "ONDE CADA UM DEVE INVESTIR PRIMEIRO" in primeira
    assert "9 cortes" in primeira           # contagem, não percentual do máximo
    assert "MURILO COSER ROCHA".title() in segunda
    assert "0,73" in segunda                # regularidade
    assert "APROVEITAMENTO POR NÍVEL" in segunda


@requer_planilha
def test_texto_da_coordenacao_no_relatorio_de_potenciais(s):
    montado = relatorio_potenciais.montar(s, textos={"GRUPO": "Química é o gargalo do grupo."})
    with pymupdf.open(stream=relatorio_potenciais.gerar(montado), filetype="pdf") as doc:
        assert "gargalo do grupo" in doc[0].get_text()


# ── unificado ───────────────────────────────────────────────────────────────────

@pytest.mark.parametrize(
    "posicao, esperado",
    [(1, "topo"), (250, "topo"), (251, "meio"), (450, "meio"), (451, "fundo"), (None, "sem")],
)
def test_faixa_da_posicao(posicao, esperado):
    assert faixa_da_posicao(posicao) == esperado


@requer_planilha
def test_panorama_do_ciclo_1_bate_com_o_relatorio(s):
    dados = montar_unificado(s)
    ciclo1 = dados.linhas[0]

    assert ciclo1.presentes == 35
    assert round(ciclo1.maior_nota, 2) == 8.61
    assert ciclo1.melhor_posicao == 84          # "84º" no relatório
    assert ciclo1.mediana_posicao == 626        # "626º" no relatório
    assert round(ciclo1.indice_1a, 2) == 2.06   # "2,06"
    assert round(ciclo1.indice_2a, 2) == 2.00   # "2,00"
    # aprovação pelo critério do Poliedro, não pelo da escola
    assert ciclo1.aprovados_1a == 7
    assert ciclo1.aprovados_2a == 1


@requer_planilha
def test_media_das_posicoes_ignora_ciclo_sem_prova(s):
    dados = montar_unificado(s)
    murilo = next(a for a in dados.ranking if a.nome.startswith("MURILO"))
    assert murilo.melhor == 84
    # só o ciclo 1 tem classificação: a média não pode ser diluída pelos vazios
    assert murilo.media_posicoes == 84


@requer_planilha
def test_pdf_unificado(s):
    dados = relatorio_unificado.gerar(relatorio_unificado.montar(s))
    with pymupdf.open(stream=dados, filetype="pdf") as doc:
        texto = "".join(p.get_text() for p in doc)
        assert doc.page_count >= 2
    assert "PANORAMA POR CICLO" in texto
    assert "84º" in texto and "626º" in texto
    assert "Sistema Poliedro" in texto


@requer_planilha
def test_pdf_avisa_quando_faltam_ciclos_do_poliedro(s):
    """Só o ciclo 1 foi importado: quem ler o ranking precisa saber que os outros
    quatro estão vazios por falta de dado, não por ausência dos alunos."""
    dados = relatorio_unificado.gerar(relatorio_unificado.montar(s))
    with pymupdf.open(stream=dados, filetype="pdf") as doc:
        assert "ranking fica incompleto" in doc[0].get_text()


@requer_planilha
def test_tabela_da_classificacao_cabe_na_pagina(s):
    """Regressão: duas metades lado a lado somavam 1008pt em 774pt úteis e a da
    direita saía cortada, sem as colunas de média e aprovações."""
    dados = relatorio_unificado.gerar(relatorio_unificado.montar(s))
    with pymupdf.open(stream=dados, filetype="pdf") as doc:
        pagina = doc[1]
        for bloco in pagina.get_text("dict")["blocks"]:
            for linha in bloco.get("lines", []):
                assert linha["bbox"][2] <= pagina.rect.width - 20, (
                    f"texto passa da margem: {linha['bbox']}"
                )


@requer_planilha
def test_nada_e_desenhado_fora_da_pagina(s):
    """Regressão: um deslocamento fixo de -190 punha a caixa "COMO LER" acima do
    topo da página, sobre o cabeçalho."""
    dados = relatorio_unificado.gerar(relatorio_unificado.montar(s))
    with pymupdf.open(stream=dados, filetype="pdf") as doc:
        for pagina in doc:
            for bloco in pagina.get_text("dict")["blocks"]:
                for linha in bloco.get("lines", []):
                    assert linha["bbox"][1] >= 0, f"texto acima do topo: {linha['bbox']}"
                    assert linha["bbox"][3] <= pagina.rect.height
