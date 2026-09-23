"""Segmentacao e recorte das questoes a partir dos PDFs das provas."""

from __future__ import annotations

from pathlib import Path

import pymupdf
import pytest

from app.config import config
from app.provas.render import renderizar
from app.provas.segment import _layout, ler

ORIGEM = config.dir_provas_origem / "CICLO 1"

# Quantas questoes cada caderno tem de verdade.
CADERNOS = {
    "Ciclo 1 - Matematica.pdf": 10,
    "Ciclo 1 - Fisica.pdf": 10,
    "Ciclo 1 - Quimica.pdf": 10,
    "Ciclo 1 - 1a Fase.pdf": 48,
    "Ciclo 1 - Portuges e Redacao.pdf": 15,
}

requer_provas = pytest.mark.skipif(
    not ORIGEM.exists(), reason="PDFs das provas ausentes (fora do versionamento)"
)


def _tinta(caminho: Path) -> float:
    """Percentual de pixels escuros — pega imagem em branco, que e o pior defeito."""
    imagem = pymupdf.Pixmap(caminho)
    dados, canais = imagem.samples, imagem.n
    escuros = sum(1 for i in range(0, len(dados), canais * 4) if dados[i] < 200)
    return escuros / (len(dados) // (canais * 4)) * 100


@requer_provas
@pytest.mark.parametrize("arquivo, esperado", CADERNOS.items())
def test_encontra_todas_as_questoes(arquivo, esperado):
    """Regressão: uma margem de topo fixa em 62pt descartava em silêncio as
    questões 5 e 8 de Física, que começam em y=46,7."""
    leitura = ler(ORIGEM / arquivo)
    assert len(leitura.recortes) == esperado
    assert leitura.numeros == list(range(1, esperado + 1))


@requer_provas
@pytest.mark.parametrize(
    "arquivo, topo",
    [
        ("Ciclo 1 - Fisica.pdf", 46.0),
        ("Ciclo 1 - Matematica.pdf", 71.0),
        ("Ciclo 1 - Quimica.pdf", 71.0),
        ("Ciclo 1 - 1a Fase.pdf", 75.0),
    ],
)
def test_margem_do_cabecalho_e_medida_por_documento(arquivo, topo):
    """O logo tem altura diferente em cada prova; uma constante única erra dos
    dois lados — alta demais pula questão, baixa demais engole o logo."""
    doc = pymupdf.open(ORIGEM / arquivo)
    try:
        assert abs(_layout(doc).topo - topo) < 1.5
    finally:
        doc.close()


@requer_provas
@pytest.mark.parametrize("arquivo", list(CADERNOS))
def test_nenhum_recorte_sai_em_branco(arquivo, tmp_path):
    """Regressão: get_pixmap(clip=...) devolve o pedaço posicionado nas coordenadas
    da página, e copy() só copia a interseção. Sem reposicionar a origem, um
    recorte do pé da página saía branco — com o arquivo do tamanho certo."""
    pdf = ORIGEM / arquivo
    leitura = ler(pdf)
    brancas = [
        r.numero
        for r in leitura.recortes
        if _tinta(renderizar(pdf, r.regioes, tmp_path).caminho) < 0.3
    ]
    assert brancas == []


@requer_provas
def test_texto_de_apoio_e_reconhecido_nas_duas_redacoes():
    """As provas anunciam o texto compartilhado de duas formas diferentes."""
    ingles = ler(ORIGEM / "Ciclo 1 - 1a Fase.pdf")      # "As questões 37 a 40 referem-se..."
    intervalos = {(a.primeira, a.ultima) for a in ingles.apoios}
    assert {(37, 40), (41, 44), (45, 48)} <= intervalos

    port = ler(ORIGEM / "Ciclo 1 - Portuges e Redacao.pdf")  # "Leia o texto a seguir..."
    assert {(1, 3), (6, 10)} <= {(a.primeira, a.ultima) for a in port.apoios}


@requer_provas
def test_folha_de_constantes_vale_para_a_prova_toda():
    """Ela não cita número de questão. Sem tratá-la, metade da prova de Química
    ficava fora dos recortes — e termodinâmica sem a constante dos gases não sai."""
    quimica = ler(ORIGEM / "Ciclo 1 - Quimica.pdf")
    assert any(a.primeira == 1 and a.ultima == 10 for a in quimica.apoios)
    assert quimica.apoios[0].serve(7)


@requer_provas
@pytest.mark.parametrize("arquivo", list(CADERNOS))
def test_cobertura_do_corpo_da_prova(arquivo):
    """Todo texto entre a primeira e a última questão precisa estar em algum recorte."""
    pdf = ORIGEM / arquivo
    leitura = ler(pdf)
    doc = pymupdf.open(pdf)
    try:
        layout = _layout(doc)
        primeira = min(m.pagina for m in leitura.marcadores)
        ultima = max(m.pagina for m in leitura.marcadores)

        faixas: dict[int, list[tuple[float, float]]] = {}
        for item in leitura.recortes + leitura.apoios:
            for regiao in item.regioes:
                faixas.setdefault(regiao.pagina, []).append((regiao.y0, regiao.y1))

        dentro = fora = 0
        for pagina in range(primeira, ultima + 1):
            for bloco in doc[pagina].get_text("dict")["blocks"]:
                for linha in bloco.get("lines", []):
                    if not "".join(s["text"] for s in linha["spans"]).strip():
                        continue
                    y0, y1 = linha["bbox"][1], linha["bbox"][3]
                    if not layout.topo <= y0 < layout.rodape:
                        continue
                    if any(a - 3 <= y0 and y1 <= b + 8 for a, b in faixas.get(pagina, [])):
                        dentro += 1
                    else:
                        fora += 1
        assert dentro / (dentro + fora) > 0.97
    finally:
        doc.close()


@requer_provas
def test_cache_reaproveita_a_imagem(tmp_path):
    pdf = ORIGEM / "Ciclo 1 - Matematica.pdf"
    regioes = ler(pdf).recortes[0].regioes
    primeira = renderizar(pdf, regioes, tmp_path)
    marca = primeira.caminho.stat().st_mtime_ns
    segunda = renderizar(pdf, regioes, tmp_path)
    assert segunda.caminho == primeira.caminho
    assert segunda.caminho.stat().st_mtime_ns == marca      # não redesenhou
