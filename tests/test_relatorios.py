"""Geracao dos relatorios em PDF."""

from __future__ import annotations

import pymupdf
import pytest

from app.analytics import metrics as M
from app.charts import svg as charts
from app.charts.svg import Barra, Segmento
from app.db import Sessao
from app.models import Fase, Materia
from app.reports import fase as relatorio_fase
from tests.conftest import requer_planilha


@pytest.fixture(scope="module")
def s():
    sessao = Sessao()
    yield sessao
    sessao.rollback()
    sessao.close()


# ── gráficos ────────────────────────────────────────────────────────────────────

def test_svg_vira_desenho_no_reportlab():
    """O mesmo SVG serve a tela e o PDF — se a conversão quebrar, os dois divergem."""
    import io

    from svglib.svglib import svg2rlg

    svg = charts.barras_horizontais(
        [Barra("F4", 23.3, "(1 q.)"), Barra("F2", 71.1, "(3 q.)")], rotulo_coluna="% DE ACERTO"
    )
    desenho = svg2rlg(io.BytesIO(svg.encode("utf-8")))
    assert desenho is not None
    assert desenho.width > 0 and desenho.height > 0


def test_barra_empilhada_respeita_a_proporcao():
    svg = charts.barra_empilhada(
        [Segmento("a", 3, charts.ACERTO), Segmento("b", 1, charts.ERRO)], largura=100
    )
    import re

    larguras = [float(x) for x in re.findall(r'<rect x="[\d.]+" y="0" width="([\d.]+)"', svg)]
    assert len(larguras) == 2
    assert larguras[0] / larguras[1] == pytest.approx(3, abs=0.1)


def test_segmento_vazio_nao_e_desenhado():
    svg = charts.barra_empilhada(
        [Segmento("a", 5, charts.ACERTO), Segmento("b", 0, charts.ERRO)], largura=100
    )
    assert svg.count("<rect") == 2      # fundo + um segmento


def test_barra_nao_estoura_com_valor_fora_da_faixa():
    for valor in (-10, 0, 150):
        svg = charts.barra_simples(valor, largura=100)
        assert "<svg" in svg


# ── PDF ─────────────────────────────────────────────────────────────────────────

@pytest.fixture(scope="module")
def pdf_1a_fase(s):
    from tests.conftest import PLANILHA

    if not PLANILHA.exists():
        pytest.skip("planilha real ausente")
    prova = M.obter_prova(s, 5, Fase.PRIMEIRA, Materia.MATEMATICA)
    return relatorio_fase.gerar(relatorio_fase.montar(s, prova))


@requer_planilha
def test_pdf_e_a4_paisagem(pdf_1a_fase):
    with pymupdf.open(stream=pdf_1a_fase, filetype="pdf") as doc:
        assert doc.page_count >= 2
        for pagina in doc:
            assert round(pagina.rect.width) == 842
            assert round(pagina.rect.height) == 595


@requer_planilha
def test_pdf_traz_os_numeros_do_relatorio(pdf_1a_fase):
    with pymupdf.open(stream=pdf_1a_fase, filetype="pdf") as doc:
        texto = "".join(p.get_text() for p in doc)
    for esperado in ("5,61", "+0,90", "26/30", "8,67", "10,00", "Ciclo 5", "1ª FASE"):
        assert esperado in texto, f"faltou {esperado}"


@requer_planilha
def test_simbolos_saem_como_unicode_de_verdade(pdf_1a_fase):
    """Os PDFs originais escrevem "≥" como um "³" em fonte Symbol, o que quebra
    copiar-e-colar e leitura por voz. Aqui tem que ser o caractere certo."""
    with pymupdf.open(stream=pdf_1a_fase, filetype="pdf") as doc:
        texto = "".join(p.get_text() for p in doc)
    assert "≥" in texto
    assert "—" in texto            # travessão, não hífen
    assert "³" not in texto        # o truque da fonte Symbol


@requer_planilha
def test_grade_nao_depende_so_da_cor(pdf_1a_fase):
    with pymupdf.open(stream=pdf_1a_fase, filetype="pdf") as doc:
        texto = doc[0].get_text()
    assert "✓" in texto and "✗" in texto


@requer_planilha
def test_rodape_sai_em_todas_as_paginas(pdf_1a_fase):
    """Regressão: o carimbo do rodapé usava Helvetica base-14, que não tem
    travessão — "Madan — Educação" virava "Madan · Educação" em silêncio."""
    with pymupdf.open(stream=pdf_1a_fase, filetype="pdf") as doc:
        total = doc.page_count
        for indice, pagina in enumerate(doc):
            texto = pagina.get_text()
            assert "Madan — Educação de Alta Performance" in texto
            assert f"Página {indice + 1} de {total}" in texto


@requer_planilha
def test_texto_da_coordenacao_substitui_o_gerado(s):
    prova = M.obter_prova(s, 5, Fase.PRIMEIRA, Materia.MATEMATICA)
    montado = relatorio_fase.montar(
        s, prova, {"ONDE A TURMA ESTÁ": "Melhor ciclo do ano até aqui."}
    )
    assert montado.textos["ONDE A TURMA ESTÁ"] == "Melhor ciclo do ano até aqui."
    assert "FRENTE MAIS FRÁGIL" in montado.textos      # os demais seguem automáticos

    with pymupdf.open(stream=relatorio_fase.gerar(montado), filetype="pdf") as doc:
        assert "Melhor ciclo do ano" in doc[0].get_text()


@requer_planilha
def test_2a_fase_traz_a_distribuicao_das_correcoes(s):
    prova = M.obter_prova(s, 5, Fase.SEGUNDA, Materia.MATEMATICA)
    dados = relatorio_fase.gerar(relatorio_fase.montar(s, prova))
    with pymupdf.open(stream=dados, filetype="pdf") as doc:
        texto = "".join(p.get_text() for p in doc)
    assert "DISTRIBUIÇÃO DAS CORREÇÕES" in texto
    assert "prova discursiva" in texto
    assert "questão zerada" in texto


@requer_planilha
def test_enunciados_entram_quando_o_pdf_da_prova_existe(s):
    """Ciclo 1 de Química tem o caderno enviado."""
    prova = M.obter_prova(s, 1, Fase.SEGUNDA, Materia.QUIMICA)
    montado = relatorio_fase.montar(s, prova)
    assert montado.enunciados

    dados = relatorio_fase.gerar(montado)
    with pymupdf.open(stream=dados, filetype="pdf") as doc:
        assert doc.page_count > 2
        assert "ENUNCIADOS DAS QUESTÕES" in doc[2].get_text()
        assert doc[2].get_images()          # o recorte está lá


@requer_planilha
def test_enunciado_ilegivel_perde_o_texto_de_apoio(s):
    """A folha de constantes de Química ocupa uma página inteira: junto de cada
    questão ela reduz o enunciado a menos de 4,5pt. Nesse caso sai só a questão,
    com aviso de onde está o apoio."""
    prova = M.obter_prova(s, 1, Fase.SEGUNDA, Materia.QUIMICA)
    dados = relatorio_fase.gerar(relatorio_fase.montar(s, prova))
    with pymupdf.open(stream=dados, filetype="pdf") as doc:
        texto = "".join(p.get_text() for p in doc)
    assert "USA A FOLHA DE APOIO" in texto


@requer_planilha
def test_nomes_longos_sao_abreviados_e_nao_cortados(s):
    """"Maria Eduarda Do Nascimen" não identifica ninguém nem cabe."""
    from app.reports.fase import encurtar_nome

    assert encurtar_nome("MARIA EDUARDA DO NASCIMENTO ZIEBELL").endswith("Ziebell")
    assert encurtar_nome("MURILO COSER ROCHA") == "Murilo Coser Rocha"
    assert "do" in encurtar_nome("GUILHERME GOMES BARAUNA DO COUTO")
