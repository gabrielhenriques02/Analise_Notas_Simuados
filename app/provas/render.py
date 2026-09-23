"""Transforma as regioes de uma questao em imagem.

As figuras das provas sao vetoriais (desenhos do Word), nao imagens embutidas: nao
da para "extrair" a figura, e preciso renderizar a pagina. O texto tambem nao serve
para exibir em exatas — a matematica vem do OMML em glifos soltos e sai como
"cosx3ya.cos³y−=". A imagem e a unica forma fiel.
"""

from __future__ import annotations

import hashlib
from dataclasses import dataclass
from pathlib import Path

import pymupdf

from app.provas.segment import Regiao

DPI = 150                 # legivel na tela sem inflar o arquivo
MARGEM_LATERAL = 24.0     # respiro nas laterais do recorte
ESPACO_ENTRE = 10         # px entre pedacos de paginas diferentes
FUNDO = (255, 255, 255)


@dataclass(frozen=True)
class Imagem:
    caminho: Path
    largura: int
    altura: int

    @property
    def nome(self) -> str:
        return self.caminho.name


def _assinatura(pdf: Path, regioes: list[Regiao], dpi: int) -> str:
    """Muda quando o PDF, as regioes ou o dpi mudam — e o cache se invalida sozinho."""
    partes = [str(pdf.resolve()), str(pdf.stat().st_mtime_ns), str(dpi)]
    partes += [f"{r.pagina}:{r.y0:.1f}:{r.y1:.1f}" for r in regioes]
    return hashlib.sha256("|".join(partes).encode()).hexdigest()[:16]


def renderizar(
    pdf: Path | str,
    regioes: list[Regiao],
    destino: Path,
    *,
    dpi: int = DPI,
    refazer: bool = False,
) -> Imagem:
    """Desenha as regioes empilhadas numa imagem so.

    Uma questao que atravessa pagina vira uma imagem continua, com um respiro entre
    os pedacos — quem le nao precisa saber onde a pagina virou.
    """
    pdf = Path(pdf)
    if not regioes:
        raise ValueError("Nenhuma região para renderizar.")

    destino.mkdir(parents=True, exist_ok=True)
    arquivo = destino / f"{_assinatura(pdf, regioes, dpi)}.png"
    if arquivo.exists() and not refazer:
        with pymupdf.open(arquivo) as pronta:
            return Imagem(arquivo, pronta[0].rect.width, pronta[0].rect.height)

    doc = pymupdf.open(pdf)
    try:
        pedacos = []
        for regiao in regioes:
            if regiao.pagina >= doc.page_count:
                continue
            pagina = doc[regiao.pagina]
            corte = pymupdf.Rect(
                max(pagina.rect.x0, MARGEM_LATERAL - 12),
                max(pagina.rect.y0, regiao.y0),
                min(pagina.rect.x1, pagina.rect.x1 - (MARGEM_LATERAL - 12)),
                min(pagina.rect.y1, regiao.y1),
            )
            if corte.height <= 2:
                continue
            pedacos.append(pagina.get_pixmap(clip=corte, dpi=dpi, alpha=False))

        if not pedacos:
            raise ValueError("As regiões não produziram nenhuma imagem.")

        largura = max(p.width for p in pedacos)
        altura = sum(p.height for p in pedacos) + ESPACO_ENTRE * (len(pedacos) - 1)

        final = pymupdf.Pixmap(pymupdf.csRGB, pymupdf.IRect(0, 0, largura, altura), False)
        final.set_rect(final.irect, FUNDO)
        topo = 0
        for pedaco in pedacos:
            # get_pixmap(clip=...) devolve o pedaco POSICIONADO onde ele estava na
            # pagina, e copy() so copia a intersecao dos retangulos. Sem reposicionar
            # a origem, um recorte do pe da pagina nao intersecta o destino e sai em
            # branco — com o arquivo do tamanho certo, que e o pior tipo de falha.
            pedaco.set_origin(0, topo)
            final.copy(pedaco, pedaco.irect)
            topo += pedaco.height + ESPACO_ENTRE

        final.save(arquivo)
        return Imagem(arquivo, largura, altura)
    finally:
        doc.close()
