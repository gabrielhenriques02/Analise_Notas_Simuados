"""Gerador de graficos em SVG.

Um so renderizador serve a tela (SVG embutido no HTML) e o PDF (convertido para
ReportLab pelo svglib). Evita manter dois codigos de grafico que divergem com o
tempo — e foi de um grafico divergente que nasceu boa parte do retrabalho aqui.

Regras seguidas (ver a orientacao de visualizacao de dados):
  - uma cor por grafico quando o comprimento ja codifica a magnitude;
  - cor de estado nunca sozinha: sempre acompanhada de rotulo;
  - ponta arredondada na extremidade do dado, reta na linha de base;
  - 2px de superficie separando segmentos que se tocam;
  - eixos e grades discretos.
"""

from __future__ import annotations

import html
from dataclasses import dataclass

# Paleta da marca, extraida dos relatorios em PDF.
NAVY = "#192b4a"
AZUL = "#2e4a73"
OURO = "#f4c62f"
ACERTO = "#2e8b57"
PARCIAL = "#7bc49c"
ATENCAO = "#e68a25"
ERRO = "#c83434"
TINTA = "#1f242e"
TINTA_2 = "#4a515e"
TINTA_3 = "#737983"
TRILHO = "#e2e5ea"
SUPERFICIE = "#ffffff"

ALTURA_BARRA = 11        # <= 24px, com folga na faixa
ESPACO = 2               # superficie separando segmentos que se tocam
RAIO = 4                 # ponta arredondada do dado


@dataclass(frozen=True)
class Barra:
    rotulo: str
    valor: float          # 0 a 100
    detalhe: str = ""
    cor: str = AZUL


@dataclass(frozen=True)
class Segmento:
    rotulo: str
    quantidade: int
    cor: str


def _esc(texto: object) -> str:
    return html.escape(str(texto), quote=True)


def _pct(valor: float) -> str:
    return f"{valor:.0f}".replace(".", ",") + "%"


def barras_horizontais(
    itens: list[Barra],
    *,
    largura: int = 340,
    rotulo_coluna: str = "",
    largura_rotulo: int = 110,
    largura_valor: int = 42,
    passo: int | None = None,
) -> str:
    """Uma barra por linha, com rotulo a esquerda e valor a direita.

    O valor vem sempre escrito: a barra mostra a ordem de grandeza, o numero
    responde "quanto exatamente".
    """
    if not itens:
        return ""

    linha = passo or (ALTURA_BARRA + 13)
    topo = 18 if rotulo_coluna else 4
    altura = topo + linha * len(itens)
    trilho_x = largura_rotulo
    trilho_largura = largura - largura_rotulo - largura_valor

    partes = [
        f'<svg xmlns="http://www.w3.org/2000/svg" width="{largura}" height="{altura}" '
        f'viewBox="0 0 {largura} {altura}" role="img">',
        f'<rect width="{largura}" height="{altura}" fill="{SUPERFICIE}"/>',
    ]
    if rotulo_coluna:
        partes.append(
            f'<text x="{largura}" y="10" text-anchor="end" font-size="8" '
            f'fill="{TINTA_3}" font-family="DejaVu Sans, Inter, Helvetica, sans-serif">'
            f"{_esc(rotulo_coluna)}</text>"
        )

    for indice, item in enumerate(itens):
        y = topo + indice * linha
        preenchido = max(0.0, min(100.0, item.valor)) / 100 * trilho_largura
        meio = y + ALTURA_BARRA / 2 + 3

        partes.append(
            f'<text x="0" y="{meio}" font-size="9" fill="{TINTA}" '
            f'font-family="DejaVu Sans, Inter, Helvetica, sans-serif">{_esc(item.rotulo)}</text>'
        )
        if item.detalhe:
            deslocamento = len(item.rotulo) * 5.2 + 6
            partes.append(
                f'<text x="{deslocamento:.0f}" y="{meio}" font-size="8" fill="{TINTA_3}" '
                f'font-family="DejaVu Sans, Inter, Helvetica, sans-serif">{_esc(item.detalhe)}</text>'
            )
        partes.append(
            f'<rect x="{trilho_x}" y="{y}" width="{trilho_largura}" height="{ALTURA_BARRA}" '
            f'rx="{ALTURA_BARRA/2:.1f}" fill="{TRILHO}"/>'
        )
        if preenchido > 0.5:
            partes.append(
                f'<rect x="{trilho_x}" y="{y}" width="{preenchido:.1f}" height="{ALTURA_BARRA}" '
                f'rx="{min(RAIO, preenchido/2):.1f}" fill="{item.cor}"/>'
            )
        partes.append(
            f'<text x="{largura}" y="{meio}" text-anchor="end" font-size="9" fill="{TINTA}" '
            f'font-family="DejaVu Sans, Inter, Helvetica, sans-serif">{_pct(item.valor)}</text>'
        )

    partes.append("</svg>")
    return "".join(partes)


def barra_empilhada(
    segmentos: list[Segmento], *, largura: int = 230, altura: int = ALTURA_BARRA
) -> str:
    """Distribuicao 100% em uma faixa, com 2px de superficie entre os pedacos."""
    total = sum(s.quantidade for s in segmentos)
    if not total:
        return ""

    visiveis = [s for s in segmentos if s.quantidade]
    vaos = ESPACO * max(0, len(visiveis) - 1)
    util = largura - vaos

    partes = [
        f'<svg xmlns="http://www.w3.org/2000/svg" width="{largura}" height="{altura}" '
        f'viewBox="0 0 {largura} {altura}" role="img">',
        f'<rect width="{largura}" height="{altura}" fill="{SUPERFICIE}"/>',
    ]
    x = 0.0
    for indice, segmento in enumerate(visiveis):
        w = segmento.quantidade / total * util
        primeiro, ultimo = indice == 0, indice == len(visiveis) - 1
        raio = min(RAIO, w / 2) if (primeiro or ultimo) else 0
        partes.append(
            f'<rect x="{x:.1f}" y="0" width="{w:.1f}" height="{altura}" '
            f'rx="{raio:.1f}" fill="{segmento.cor}">'
            f"<title>{_esc(segmento.rotulo)}: {segmento.quantidade}</title></rect>"
        )
        x += w + ESPACO
    partes.append("</svg>")
    return "".join(partes)


def barra_simples(valor: float, *, largura: int = 120, cor: str = AZUL) -> str:
    """Barra sozinha, para acompanhar um numero ja escrito ao lado."""
    preenchido = max(0.0, min(100.0, valor)) / 100 * largura
    return (
        f'<svg xmlns="http://www.w3.org/2000/svg" width="{largura}" height="{ALTURA_BARRA}" '
        f'viewBox="0 0 {largura} {ALTURA_BARRA}" role="img">'
        f'<rect width="{largura}" height="{ALTURA_BARRA}" rx="{ALTURA_BARRA/2:.1f}" fill="{TRILHO}"/>'
        + (
            f'<rect width="{preenchido:.1f}" height="{ALTURA_BARRA}" '
            f'rx="{min(RAIO, preenchido/2):.1f}" fill="{cor}"/>'
            if preenchido > 0.5
            else ""
        )
        + "</svg>"
    )
