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
    valor: float              # 0 a 100, define o comprimento
    detalhe: str = ""
    cor: str = AZUL
    texto: str = ""           # o que aparece a direita; vazio = o proprio percentual


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
            # alinhado ao fim da faixa do rotulo: calcular por numero de caracteres
            # fazia o detalhe entrar por baixo da barra em rotulos curtos
            partes.append(
                f'<text x="{trilho_x - 5}" y="{meio}" text-anchor="end" font-size="7.5" '
                f'fill="{TINTA_3}" '
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
            f'font-family="DejaVu Sans, Inter, Helvetica, sans-serif">'
            f'{_esc(item.texto) if item.texto else _pct(item.valor)}</text>'
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


def _escala_do_eixo(maximo: float, marcas_alvo: int = 5) -> tuple[float, float]:
    """Devolve (teto, passo) em numeros redondos, com a menor folga possivel.

    Uma marca de 47% nao ajuda ninguem a ler, e um teto de 80% para um maximo de
    40% espreme as colunas a metade da altura. Entre os passos redondos, vence o
    que der o teto mais baixo com um numero confortavel de marcas.
    """
    import math

    if maximo <= 0:
        return 1.0, 1.0

    alvo = maximo * 1.08
    potencia = 10 ** math.floor(math.log10(alvo))
    candidatos = []
    for escala in (potencia / 10, potencia, potencia * 10):
        for multiplo in (1, 2, 2.5, 5):
            passo = multiplo * escala
            if passo <= 0:
                continue
            teto = math.ceil(alvo / passo) * passo
            marcas = round(teto / passo) + 1
            if marcas_alvo - 1 <= marcas <= marcas_alvo + 2:
                candidatos.append((teto, marcas, passo))
    if not candidatos:
        return float(alvo), float(alvo / max(1, marcas_alvo - 1))
    teto, _, passo = min(candidatos, key=lambda c: (c[0], c[1]))
    return float(teto), float(passo)


@dataclass(frozen=True)
class Coluna:
    rotulo: str
    valor: float
    acima: str = ""       # rotulo desenhado sobre a coluna
    abaixo: str = ""      # segunda linha sob o eixo
    cor: str = AZUL


def colunas_verticais(
    itens: list[Coluna],
    *,
    largura: int = 430,
    altura: int = 170,
    maximo: float | None = None,
    sufixo: str = "%",
    marcas: int = 5,
) -> str:
    """Colunas com eixo y discreto e o valor escrito sobre cada uma."""
    if not itens:
        return ""

    topo, base = 14, altura - 32
    esquerda = 34
    if maximo:
        teto, passo_eixo = float(maximo), float(maximo) / max(1, marcas - 1)
    else:
        teto, passo_eixo = _escala_do_eixo(max(i.valor for i in itens), marcas)
    marcas = int(round(teto / passo_eixo)) + 1
    faixa = (largura - esquerda - 8) / len(itens)
    grossura = min(30.0, faixa * 0.5)

    def y_de(valor: float) -> float:
        return base - (valor / teto) * (base - topo)

    fonte = 'font-family="DejaVu Sans, Inter, Helvetica, sans-serif"'
    partes = [
        f'<svg xmlns="http://www.w3.org/2000/svg" width="{largura}" height="{altura}" '
        f'viewBox="0 0 {largura} {altura}" role="img">',
        f'<rect width="{largura}" height="{altura}" fill="{SUPERFICIE}"/>',
    ]

    for indice in range(marcas):
        valor = passo_eixo * indice
        y = y_de(valor)
        partes.append(
            f'<line x1="{esquerda}" y1="{y:.1f}" x2="{largura - 4}" y2="{y:.1f}" '
            f'stroke="{TRILHO}" stroke-width="0.8"/>'
        )
        marca = f"{valor:.0f}".replace(".", ",") + sufixo
        partes.append(
            f'<text x="{esquerda - 5}" y="{y + 3:.1f}" text-anchor="end" font-size="7.5" '
            f'fill="{TINTA_3}" {fonte}>{_esc(marca)}</text>'
        )

    for indice, item in enumerate(itens):
        centro = esquerda + faixa * (indice + 0.5)
        x = centro - grossura / 2
        y = y_de(item.valor)
        alto = max(0.0, base - y)
        if alto > 0.5:
            partes.append(
                f'<rect x="{x:.1f}" y="{y:.1f}" width="{grossura:.1f}" height="{alto:.1f}" '
                f'rx="{min(RAIO, grossura / 2):.1f}" fill="{item.cor}">'
                f"<title>{_esc(item.rotulo)}: {_esc(item.acima or item.valor)}</title></rect>"
            )
        if item.acima:
            partes.append(
                f'<text x="{centro:.1f}" y="{y - 4:.1f}" text-anchor="middle" font-size="8" '
                f'fill="{TINTA}" {fonte}>{_esc(item.acima)}</text>'
            )
        partes.append(
            f'<text x="{centro:.1f}" y="{base + 12:.1f}" text-anchor="middle" font-size="7.5" '
            f'fill="{TINTA_2}" {fonte}>{_esc(item.rotulo)}</text>'
        )
        if item.abaixo:
            partes.append(
                f'<text x="{centro:.1f}" y="{base + 22:.1f}" text-anchor="middle" font-size="7" '
                f'fill="{TINTA_3}" {fonte}>{_esc(item.abaixo)}</text>'
            )

    partes.append(
        f'<line x1="{esquerda}" y1="{base:.1f}" x2="{largura - 4}" y2="{base:.1f}" '
        f'stroke="{TINTA_3}" stroke-width="0.9"/>'
    )
    partes.append("</svg>")
    return "".join(partes)


@dataclass(frozen=True)
class Serie:
    rotulo: str
    valores: list[float | None]      # None = ponto ausente, a linha se interrompe
    cor: str = AZUL
    rotular_pontos: bool = False


@dataclass(frozen=True)
class Referencia:
    valor: float
    rotulo: str = ""
    cor: str = TINTA_3


def linhas(
    series: list[Serie],
    categorias: list[str],
    *,
    largura: int = 430,
    altura: int = 190,
    minimo: float = 0.0,
    maximo: float | None = None,
    invertido: bool = False,
    sufixo: str = "",
    referencias: list[Referencia] | None = None,
    formatar=None,
    rotulos_a_direita: bool = False,
) -> str:
    """Linhas sobre categorias. `invertido` serve para ranking, onde 1º fica no alto."""
    if not series or not categorias:
        return ""

    formatar = formatar or (lambda v: f"{v:.2f}".replace(".", ",") + sufixo)
    fonte = 'font-family="DejaVu Sans, Inter, Helvetica, sans-serif"'
    reserva = 96 if rotulos_a_direita else 8
    esquerda, topo = 38, 12
    base = altura - 26
    direita = largura - reserva

    valores = [v for s in series for v in s.valores if v is not None]
    if not valores:
        return ""
    teto = maximo if maximo is not None else max(valores)
    piso = minimo
    if teto <= piso:
        teto = piso + 1
    passo_eixo = (teto - piso) / 4

    def y_de(valor: float) -> float:
        proporcao = (valor - piso) / (teto - piso)
        if invertido:
            return topo + proporcao * (base - topo)
        return base - proporcao * (base - topo)

    def x_de(indice: int) -> float:
        if len(categorias) == 1:
            return (esquerda + direita) / 2
        return esquerda + indice * (direita - esquerda) / (len(categorias) - 1)

    partes = [
        f'<svg xmlns="http://www.w3.org/2000/svg" width="{largura}" height="{altura}" '
        f'viewBox="0 0 {largura} {altura}" role="img">',
        f'<rect width="{largura}" height="{altura}" fill="{SUPERFICIE}"/>',
    ]

    for indice in range(5):
        valor = piso + passo_eixo * indice
        y = y_de(valor)
        partes.append(
            f'<line x1="{esquerda}" y1="{y:.1f}" x2="{direita}" y2="{y:.1f}" '
            f'stroke="{TRILHO}" stroke-width="0.8"/>'
        )
        partes.append(
            f'<text x="{esquerda - 5}" y="{y + 3:.1f}" text-anchor="end" font-size="7" '
            f'fill="{TINTA_3}" {fonte}>{_esc(formatar(valor))}</text>'
        )

    for referencia in referencias or []:
        y = y_de(referencia.valor)
        partes.append(
            f'<line x1="{esquerda}" y1="{y:.1f}" x2="{direita}" y2="{y:.1f}" '
            f'stroke="{referencia.cor}" stroke-width="1" stroke-dasharray="4 3"/>'
        )
        if referencia.rotulo:
            partes.append(
                f'<text x="{direita}" y="{y - 3:.1f}" text-anchor="end" font-size="6.8" '
                f'fill="{referencia.cor}" {fonte}>{_esc(referencia.rotulo)}</text>'
            )

    for indice, categoria in enumerate(categorias):
        partes.append(
            f'<text x="{x_de(indice):.1f}" y="{base + 13:.1f}" text-anchor="middle" '
            f'font-size="7" fill="{TINTA_2}" {fonte}>{_esc(categoria)}</text>'
        )

    for serie in series:
        trecho: list[tuple[float, float]] = []
        for indice, valor in enumerate(serie.valores):
            if valor is None:
                if len(trecho) > 1:
                    partes.append(_traco(trecho, serie.cor))
                trecho = []
                continue
            trecho.append((x_de(indice), y_de(valor)))
        if len(trecho) > 1:
            partes.append(_traco(trecho, serie.cor))

        for indice, valor in enumerate(serie.valores):
            if valor is None:
                continue
            x, y = x_de(indice), y_de(valor)
            partes.append(
                f'<circle cx="{x:.1f}" cy="{y:.1f}" r="3" fill="{serie.cor}" '
                f'stroke="{SUPERFICIE}" stroke-width="2"><title>'
                f"{_esc(serie.rotulo)} · {_esc(categorias[indice])}: {_esc(formatar(valor))}"
                "</title></circle>"
            )
            if serie.rotular_pontos:
                partes.append(
                    f'<text x="{x:.1f}" y="{y - 7:.1f}" text-anchor="middle" font-size="6.8" '
                    f'fill="{TINTA}" {fonte}>{_esc(formatar(valor))}</text>'
                )

        if rotulos_a_direita:
            ultimo = next(
                (
                    (i, v) for i, v in reversed(list(enumerate(serie.valores)))
                    if v is not None
                ),
                None,
            )
            if ultimo:
                indice, valor = ultimo
                partes.append(
                    f'<text x="{x_de(indice) + 7:.1f}" y="{y_de(valor) + 3:.1f}" font-size="7" '
                    f'fill="{TINTA_2}" {fonte}>{_esc(serie.rotulo)}</text>'
                )

    partes.append("</svg>")
    return "".join(partes)


def _traco(pontos: list[tuple[float, float]], cor: str) -> str:
    caminho = " ".join(
        ("M" if indice == 0 else "L") + f"{x:.1f} {y:.1f}"
        for indice, (x, y) in enumerate(pontos)
    )
    return (
        f'<path d="{caminho}" fill="none" stroke="{cor}" stroke-width="2" '
        'stroke-linejoin="round" stroke-linecap="round"/>'
    )
