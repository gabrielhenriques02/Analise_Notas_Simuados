"""Base dos relatorios em PDF.

A4 paisagem, como os relatorios atuais. O visual foi renovado a pedido da
coordenacao: corpo de 7-8pt no lugar dos 5-6pt originais, fonte incorporada e
simbolos Unicode de verdade — os PDFs antigos escrevem "≥" como um "³" em fonte
Symbol, o que quebra copia e colagem e leitura por voz.
"""

from __future__ import annotations

import io
from dataclasses import dataclass, field
from pathlib import Path

from reportlab.lib.colors import HexColor
from reportlab.lib.utils import ImageReader
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
from reportlab.pdfgen.canvas import Canvas

from app.charts import svg as charts

PAGINA = (841.89, 595.27)          # A4 paisagem, igual aos relatorios atuais
MARGEM = 34.0
LARGURA_UTIL = PAGINA[0] - 2 * MARGEM

# A Inter esta instalada, mas so em .otf com contornos PostScript, que o ReportLab
# nao le. A DejaVu cobre acento, "≥", "−" e "º" — que e o que o relatorio precisa.
FONTES = {
    "corpo": ("/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf", "Relatorio"),
    "forte": ("/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf", "Relatorio-Bold"),
}
CORPO = "Relatorio"
FORTE = "Relatorio-Bold"

_registradas = False


def registrar_fontes() -> None:
    global _registradas
    if _registradas:
        return
    for caminho, nome in FONTES.values():
        if Path(caminho).exists():
            pdfmetrics.registerFont(TTFont(nome, caminho))
    _registradas = True


def cor(valor: str):
    return HexColor(valor)


PARTICULAS = {"da", "de", "do", "das", "dos", "e"}


def encurtar_nome(nome: str, limite: float, tamanho: float = 7.4) -> str:
    """Abrevia os nomes do meio em vez de cortar no meio de uma palavra.

    "Maria Eduarda do Nascimento Ziebell" vira "Maria E. do N. Ziebell", que ainda
    identifica a pessoa — "Maria Eduarda Do Nascimen" nao identifica nem cabe.
    """
    registrar_fontes()
    partes = [
        p.lower() if p.lower() in PARTICULAS else p
        for p in nome.title().split()
    ]
    if not partes:
        return nome

    def largura(texto: str) -> float:
        return pdfmetrics.stringWidth(texto, CORPO, tamanho)

    atual = " ".join(partes)
    meio = 1
    while largura(atual) > limite and meio < len(partes) - 1:
        if partes[meio].lower() not in PARTICULAS:
            partes[meio] = partes[meio][0] + "."
        meio += 1
        atual = " ".join(partes)

    while largura(atual) > limite and len(partes) > 2:
        del partes[1]
        atual = " ".join(partes)
    return atual


@dataclass
class Rodape:
    esquerda: str
    direita_formato: str = "Página {pagina} de {total}"


@dataclass
class Documento:
    """Desenha por coordenadas, com a origem no alto — o layout e denso e
    posicionado, nao um fluxo de paragrafos."""

    titulo: str
    subtitulo: str
    rodape: Rodape
    turma: str = "TURMA ITA 2026"
    separador: str = "  ·  "

    _buffer: io.BytesIO = field(default_factory=io.BytesIO, init=False)
    _canvas: Canvas = field(init=False)
    _pagina: int = field(default=0, init=False)
    _eyebrow: str = field(default="", init=False)

    def __post_init__(self) -> None:
        registrar_fontes()
        self._canvas = Canvas(self._buffer, pagesize=PAGINA)
        self._canvas.setTitle(self.titulo)
        self._canvas.setAuthor("Madan — Educação de Alta Performance")

    # ── sistema de coordenadas ──────────────────────────────────────────────────

    def _y(self, de_cima: float) -> float:
        return PAGINA[1] - de_cima

    # ── pagina ──────────────────────────────────────────────────────────────────

    def nova_pagina(self, eyebrow: str = "", compacto: bool = False) -> float:
        """Abre uma pagina e devolve a altura livre logo abaixo do cabecalho."""
        if self._pagina:
            self._canvas.showPage()
        self._pagina += 1
        self._eyebrow = eyebrow
        return self._cabecalho(compacto)

    def _cabecalho(self, compacto: bool) -> float:
        c = self._canvas
        titulo = self.titulo if not compacto else self.titulo.upper()
        tamanho = 15 if not compacto else 11

        c.setFillColor(cor(charts.NAVY))
        c.setFont(FORTE, tamanho)
        c.drawString(MARGEM, self._y(38), titulo)

        c.setFont(CORPO, 8.2)
        c.setFillColor(cor(charts.TINTA_3))
        c.drawString(MARGEM, self._y(52), self.subtitulo)

        if self._eyebrow:
            c.setFont(FORTE, 7.6)
            c.setFillColor(cor(charts.AZUL))
            c.drawRightString(PAGINA[0] - MARGEM, self._y(38), self._eyebrow)
        c.setFont(CORPO, 7.6)
        c.setFillColor(cor(charts.TINTA_3))
        c.drawRightString(PAGINA[0] - MARGEM, self._y(52), self.turma)

        # regua dourada da marca
        c.setFillColor(cor(charts.OURO))
        c.rect(MARGEM, self._y(60), 54, 2.4, stroke=0, fill=1)
        c.setFillColor(cor("#e2e5ea"))
        c.rect(MARGEM + 58, self._y(60), LARGURA_UTIL - 58, 0.7, stroke=0, fill=1)

        return 74.0

    def _rodape(self, total: int) -> None:
        c = self._canvas
        c.setFont(CORPO, 7)
        c.setFillColor(cor(charts.TINTA_3))
        c.drawString(MARGEM, self._y(PAGINA[1] - 16), self.rodape.esquerda)
        c.drawRightString(
            PAGINA[0] - MARGEM,
            self._y(PAGINA[1] - 16),
            self.rodape.direita_formato.format(pagina=self._pagina, total=total),
        )

    # ── blocos ──────────────────────────────────────────────────────────────────

    def secao(self, y: float, titulo: str, legenda: str = "") -> float:
        c = self._canvas
        c.setFillColor(cor(charts.NAVY))
        c.rect(MARGEM, self._y(y + 8.5), 2.5, 9, stroke=0, fill=1)
        c.setFont(FORTE, 8.4)
        c.drawString(MARGEM + 8, self._y(y + 7), titulo.upper())
        avanco = 14.0
        if legenda:
            c.setFont(CORPO, 7.4)
            c.setFillColor(cor(charts.TINTA_3))
            c.drawString(MARGEM + 8, self._y(y + 18), legenda)
            avanco = 25.0
        return y + avanco

    def indicadores(self, y: float, cartoes: list[tuple[str, str, str]]) -> float:
        """Faixa de KPIs: rotulo pequeno, numero grande, nota embaixo."""
        if not cartoes:
            return y
        largura = LARGURA_UTIL / len(cartoes)
        c = self._canvas
        for indice, (rotulo, valor, nota) in enumerate(cartoes):
            x = MARGEM + indice * largura
            c.setFillColor(cor("#f8f9fb"))
            c.roundRect(x, self._y(y + 46), largura - 8, 46, 4, stroke=0, fill=1)
            c.setFillColor(cor(charts.TINTA_3))
            c.setFont(CORPO, 6.8)
            c.drawString(x + 9, self._y(y + 14), rotulo.upper())
            c.setFillColor(cor(charts.TINTA))
            c.setFont(FORTE, 17)
            c.drawString(x + 9, self._y(y + 32), valor)
            c.setFillColor(cor(charts.TINTA_3))
            c.setFont(CORPO, 6.8)
            c.drawString(x + 9, self._y(y + 42), nota)
        return y + 56

    def tabela(
        self,
        y: float,
        cabecalhos: list[str],
        linhas: list[list[str]],
        larguras: list[float],
        *,
        x: float = MARGEM,
        alinhamento: str | None = None,
        zebra: bool = True,
        altura_linha: float = 13.0,
        pintar=None,
        marcar=None,
    ) -> float:
        """`pintar(linha, coluna, texto)` devolve (fundo, tinta) ou None.
        `marcar(linha)` devolve True para destacar a linha com uma faixa a esquerda."""
        c = self._canvas
        alinhamento = alinhamento or "l" * len(cabecalhos)

        c.setFont(FORTE, 6.8)
        c.setFillColor(cor(charts.TINTA_3))
        posicao = x
        for indice, titulo in enumerate(cabecalhos):
            if alinhamento[indice] == "r":
                c.drawRightString(posicao + larguras[indice] - 4, self._y(y + 8), titulo.upper())
            else:
                c.drawString(posicao + 2, self._y(y + 8), titulo.upper())
            posicao += larguras[indice]
        y += 11
        c.setStrokeColor(cor("#c7ccd4"))
        c.setLineWidth(0.6)
        c.line(x, self._y(y), x + sum(larguras), self._y(y))
        y += 2

        for numero, linha in enumerate(linhas):
            if marcar and marcar(numero):
                c.setFillColor(cor(charts.ERRO))
                c.rect(x - 2.5, self._y(y + altura_linha), 2.2, altura_linha, stroke=0, fill=1)
            if zebra and numero % 2:
                c.setFillColor(cor("#fafbfc"))
                c.rect(x, self._y(y + altura_linha), sum(larguras), altura_linha, stroke=0, fill=1)
            posicao = x
            for indice, celula in enumerate(linha):
                pintura = pintar(numero, indice, celula) if pintar else None
                if pintura:
                    fundo, tinta = pintura
                    if fundo:
                        c.setFillColor(cor(fundo))
                        c.roundRect(
                            posicao + 1, self._y(y + altura_linha - 1.5),
                            larguras[indice] - 2, altura_linha - 3, 2, stroke=0, fill=1,
                        )
                    c.setFillColor(cor(tinta))
                else:
                    c.setFillColor(cor(charts.TINTA))
                c.setFont(CORPO, 7.4)
                if alinhamento[indice] == "r":
                    c.drawRightString(posicao + larguras[indice] - 4, self._y(y + altura_linha - 4), celula)
                elif alinhamento[indice] == "c":
                    c.drawCentredString(posicao + larguras[indice] / 2, self._y(y + altura_linha - 4), celula)
                else:
                    c.drawString(posicao + 2, self._y(y + altura_linha - 4), celula)
                posicao += larguras[indice]
            y += altura_linha
        return y

    def texto(self, y: float, conteudo: str, *, x: float = MARGEM, largura: float = LARGURA_UTIL,
              tamanho: float = 7.6, cor_texto: str = charts.TINTA_2, entrelinha: float = 10.0) -> float:
        """Paragrafo com quebra simples por largura."""
        c = self._canvas
        c.setFont(CORPO, tamanho)
        c.setFillColor(cor(cor_texto))
        palavras = conteudo.split()
        linha = ""
        for palavra in palavras:
            teste = f"{linha} {palavra}".strip()
            if pdfmetrics.stringWidth(teste, CORPO, tamanho) > largura and linha:
                c.drawString(x, self._y(y + tamanho), linha)
                y += entrelinha
                linha = palavra
            else:
                linha = teste
        if linha:
            c.drawString(x, self._y(y + tamanho), linha)
            y += entrelinha
        return y

    def rotulo(self, y: float, texto: str, *, x: float = MARGEM, tamanho: float = 7.2,
               forte: bool = False, cor_texto: str = charts.TINTA_3) -> float:
        c = self._canvas
        c.setFont(FORTE if forte else CORPO, tamanho)
        c.setFillColor(cor(cor_texto))
        c.drawString(x, self._y(y + tamanho), texto)
        return y + tamanho + 3

    def etiqueta(self, y: float, x: float, texto: str, fundo: str, tinta: str,
                 *, tamanho: float = 6.4) -> float:
        c = self._canvas
        largura = pdfmetrics.stringWidth(texto, FORTE, tamanho) + 9
        c.setFillColor(cor(fundo))
        c.roundRect(x, self._y(y + 9.5), largura, 9, 4.5, stroke=0, fill=1)
        c.setFillColor(cor(tinta))
        c.setFont(FORTE, tamanho)
        c.drawString(x + 4.5, self._y(y + 7), texto)
        return largura + 4

    def grafico(self, y: float, svg_texto: str, *, x: float = MARGEM, escala: float = 1.0) -> float:
        """Coloca um SVG do modulo de graficos — o mesmo que a tela usa."""
        from reportlab.graphics import renderPDF
        from svglib.svglib import svg2rlg

        if not svg_texto.strip():
            return y
        desenho = svg2rlg(io.BytesIO(svg_texto.encode("utf-8")))
        if desenho is None:
            return y
        desenho.scale(escala, escala)
        altura = desenho.height * escala
        renderPDF.draw(desenho, self._canvas, x, self._y(y + altura))
        return y + altura + 4

    def imagem(self, y: float, caminho: Path, *, x: float = MARGEM,
               largura_max: float = LARGURA_UTIL, altura_max: float = 300.0) -> float:
        leitor = ImageReader(str(caminho))
        larg, alt = leitor.getSize()
        escala = min(largura_max / larg, altura_max / alt, 1.0)
        larg, alt = larg * escala, alt * escala
        self._canvas.drawImage(leitor, x, self._y(y + alt), larg, alt, mask="auto")
        return y + alt + 4

    def linha_fina(self, y: float, *, x: float = MARGEM, largura: float = LARGURA_UTIL) -> float:
        self._canvas.setFillColor(cor("#e2e5ea"))
        self._canvas.rect(x, self._y(y), largura, 0.6, stroke=0, fill=1)
        return y + 6

    # ── finalizacao ─────────────────────────────────────────────────────────────

    def gerar(self) -> bytes:
        """Fecha o documento e escreve o rodape com o total de paginas correto."""
        total = self._pagina
        self._canvas.showPage()
        self._canvas.save()

        # O total de paginas so e conhecido no fim: reabre e carimba o rodape.
        import pymupdf

        doc = pymupdf.open(stream=self._buffer.getvalue(), filetype="pdf")
        try:
            # A Helvetica base-14 nao tem travessao nem "≥": carimbar o rodape com
            # ela trocava "Madan — Educação" por "Madan · Educação" em silencio.
            arquivo_fonte = FONTES["corpo"][0]
            usa_dejavu = Path(arquivo_fonte).exists()
            nome_fonte = "rodape" if usa_dejavu else "helv"

            for indice in range(min(total, doc.page_count)):
                pagina = doc[indice]
                if usa_dejavu:
                    pagina.insert_font(fontname=nome_fonte, fontfile=arquivo_fonte)
                pagina.insert_text(
                    (MARGEM, PAGINA[1] - 16),
                    self.rodape.esquerda,
                    fontname=nome_fonte,
                    fontfile=arquivo_fonte if usa_dejavu else None,
                    fontsize=7, color=(0.45, 0.47, 0.51),
                )
                direita = self.rodape.direita_formato.format(pagina=indice + 1, total=total)
                largura = pymupdf.get_text_length(
                    direita, "helv", 7
                ) if not usa_dejavu else pymupdf.Font(fontfile=arquivo_fonte).text_length(direita, 7)
                pagina.insert_text(
                    (PAGINA[0] - MARGEM - largura, PAGINA[1] - 16),
                    direita,
                    fontname=nome_fonte,
                    fontfile=arquivo_fonte if usa_dejavu else None,
                    fontsize=7, color=(0.45, 0.47, 0.51),
                )
            if doc.page_count > total:
                doc.delete_page(doc.page_count - 1)
            return doc.tobytes()
        finally:
            doc.close()
