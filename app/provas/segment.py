"""Localiza cada questao dentro do PDF da prova.

As provas sao nativas do Word e os marcadores sao regulares: "Questão n." em
Arial-Bold 10pt na margem esquerda (x=36). Isso e confiavel o bastante para propor
os recortes sozinho — mas a coordenacao revisa antes de valer, porque questao que
atravessa pagina e enunciado compartilhado nao tem regra perfeita.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path

import pymupdf

# "Questão 1." na prova, "QUESTÃO 01" na resolucao. O kerning do Word separa os
# digitos ("Questão 1 0 ."), por isso os dois grupos soltos.
MARCADOR = re.compile(r"^\s*(?:QUEST[ÃA]O|Quest[ãa]o)\s*(\d)\s*(\d)?\s*[.\-–)]?\s", re.I)

# As duas formas que as provas usam para anunciar um texto compartilhado:
#   "As questões 41 a 44 referem-se ao texto a seguir:"        (1ª fase, inglês)
#   "Leia o texto a seguir para responder às questões de 01 a 03."  (português)
APOIO = re.compile(
    r"quest(?:ões|oes)\s+(?:de\s+)?(\d{1,2})\s*(?:a|e|até)\s*(\d{1,2})", re.I
)
APOIO_GATILHO = re.compile(r"(referem|refere|baseiam|leia|responder|com base)", re.I)

# A folha de constantes nao cita numero de questao: ela vale para a prova inteira
# daquela materia. Sem trata-la, quase metade da prova de Quimica ficava fora dos
# recortes — uma questao de termodinamica sem a constante dos gases nao se resolve.
CONSTANTES = re.compile(r"^\s*(constantes|dados|massas?\s+molares?)\s*:?\s*$", re.I)

# Limites de seguranca. Os de verdade sao medidos por documento em _layout(),
# porque o logo do cabecalho tem altura diferente em cada prova: ele termina em
# y=45 na de Fisica, y=70 na de Matematica e y=74 na de 1ª fase. Uma constante
# unica erra dos dois lados — 62 descartava em silencio as questoes 5 e 8 de
# Fisica, e 40 fazia o recorte da 1ª fase engolir o logo.
MARGEM_TOPO = 36.0
MARGEM_RODAPE = 812.0
FOLGA = 6.0              # respiro acima do marcador, para o recorte nao cortar rente


@dataclass(frozen=True)
class Marcador:
    numero: int
    pagina: int
    y: float
    texto: str


@dataclass(frozen=True)
class Regiao:
    """Um pedaco de pagina. Uma questao pode ocupar varios."""

    pagina: int
    y0: float
    y1: float

    @property
    def altura(self) -> float:
        return self.y1 - self.y0


@dataclass
class BlocoApoio:
    """Texto ou tabela que serve a mais de uma questao.

    Recortar a questao 42 sozinha perderia o texto em ingles que ela interpreta;
    a folha de constantes de Quimica tem o mesmo papel.
    """

    primeira: int
    ultima: int
    regioes: list[Regiao]
    descricao: str

    def serve(self, numero: int) -> bool:
        return self.primeira <= numero <= self.ultima


@dataclass
class Recorte:
    numero: int
    regioes: list[Regiao]
    apoio: BlocoApoio | None = None

    @property
    def pagina_ini(self) -> int:
        return self.regioes[0].pagina

    @property
    def atravessa_pagina(self) -> bool:
        return len(self.regioes) > 1

    @property
    def altura_total(self) -> float:
        return sum(r.altura for r in self.regioes)


@dataclass
class Leitura:
    caminho: Path
    paginas: int
    marcadores: list[Marcador] = field(default_factory=list)
    recortes: list[Recorte] = field(default_factory=list)
    apoios: list[BlocoApoio] = field(default_factory=list)
    avisos: list[str] = field(default_factory=list)

    @property
    def numeros(self) -> list[int]:
        return [r.numero for r in self.recortes]


@dataclass(frozen=True)
class Layout:
    """Onde comeca e termina o conteudo, medido neste documento."""

    topo: float
    rodape: float


def _layout(doc) -> Layout:
    """Acha o pe do cabecalho e o teto do rodape observando as paginas.

    O cabecalho e uma imagem repetida no alto de cada pagina; o rodape juridico e
    um texto repetido no pe. Medir e mais seguro do que fixar: outro ciclo pode vir
    com outro layout e o segmentador continua valendo.
    """
    # O cabecalho e a imagem que reaparece no alto de quase toda pagina. Pegar
    # "qualquer imagem no topo" confunde o logo com uma figura da propria questao.
    # A chave inclui o x: sem ele, tres figuras diferentes de quimica na mesma
    # faixa vertical somavam como se fossem uma imagem repetida, e o topo ia parar
    # em y=137 — quatro questoes sumiam. E o cabecalho comeca colado no topo, o que
    # o separa de qualquer figura do enunciado.
    repeticoes: dict[tuple[int, int, int], int] = {}
    for pagina in doc:
        for info in pagina.get_image_info():
            caixa = info["bbox"]
            if caixa[1] < 45:
                chave = (round(caixa[0]), round(caixa[1]), round(caixa[3]))
                repeticoes[chave] = repeticoes.get(chave, 0) + 1

    minimo = max(2, doc.page_count // 2)
    cabecalhos = [alto for (_, _, alto), vezes in repeticoes.items() if vezes >= minimo]
    topo = (max(cabecalhos) + 1.0) if cabecalhos else MARGEM_TOPO

    inicio_rodape = []
    for pagina in doc:
        for bloco in pagina.get_text("dict")["blocks"]:
            for linha in bloco.get("lines", []):
                if "Aviso Legal" in "".join(s["text"] for s in linha["spans"]):
                    inicio_rodape.append(linha["bbox"][1])
    rodape = (min(inicio_rodape) - 4.0) if inicio_rodape else MARGEM_RODAPE

    return Layout(max(topo, MARGEM_TOPO), min(rodape, MARGEM_RODAPE))


def _mobilia(doc) -> set[tuple[int, int, int]]:
    """Caixas que se repetem na mesma posicao em varias paginas.

    Logo, cabecalho e rodape juridico aparecem em quase toda pagina; o conteudo de
    uma questao, nao. Detectar em vez de fixar coordenadas mantem o segmentador
    valido para provas de outros ciclos, que podem ter outro layout.
    """
    if doc.page_count < 3:
        return set()
    contagem: dict[tuple[int, int, int], int] = {}
    for pagina in doc:
        vistos = set()
        for item in pagina.get_image_info() + [
            {"bbox": d["rect"]} for d in pagina.get_drawings()
        ]:
            caixa = item["bbox"]
            chave = (round(caixa[0] / 4), round(caixa[1] / 4), round(caixa[3] / 4))
            vistos.add(chave)
        for chave in vistos:
            contagem[chave] = contagem.get(chave, 0) + 1
    minimo = max(3, doc.page_count // 2)
    return {chave for chave, vezes in contagem.items() if vezes >= minimo}


def _fim_do_conteudo(pagina, y0: float, y1: float, mobilia: set, rodape: float) -> float:
    """Ate onde o conteudo de fato vai dentro da faixa, ignorando a mobilia.

    Sem isso o recorte se estica ate o pe da pagina e engole o logo do rodape mais
    um palmo de branco.
    """
    fundo = y0
    for bloco in pagina.get_text("dict")["blocks"]:
        for linha in bloco.get("lines", []):
            if not "".join(s["text"] for s in linha["spans"]).strip():
                continue
            topo, base = linha["bbox"][1], linha["bbox"][3]
            if y0 - 2 <= topo < y1 and base < rodape:
                fundo = max(fundo, base)

    for item in pagina.get_image_info() + [
        {"bbox": d["rect"]} for d in pagina.get_drawings()
    ]:
        caixa = item["bbox"]
        chave = (round(caixa[0] / 4), round(caixa[1] / 4), round(caixa[3] / 4))
        if chave in mobilia:
            continue
        if y0 - 2 <= caixa[1] < y1 and caixa[3] < rodape:
            fundo = max(fundo, caixa[3])

    return min(y1, fundo + FOLGA) if fundo > y0 else y1


def _linhas(pagina) -> list[tuple[float, float, str, bool]]:
    saida = []
    for bloco in pagina.get_text("dict")["blocks"]:
        for linha in bloco.get("lines", []):
            texto = "".join(s["text"] for s in linha["spans"])
            if texto.strip():
                negrito = any("Bold" in s.get("font", "") for s in linha["spans"])
                saida.append((linha["bbox"][1], linha["bbox"][3], texto, negrito))
    saida.sort(key=lambda x: x[0])
    return saida


def _ultima_pagina_com_texto(doc, layout: Layout) -> int:
    """As provas terminam com paginas em branco que so tem cabecalho e rodape."""
    ultima = 0
    for i, pagina in enumerate(doc):
        corpo = [
            t for y0, _, t, _ in _linhas(pagina)
            if layout.topo <= y0 < layout.rodape and len(t.strip()) > 3
        ]
        if corpo:
            ultima = i
    return ultima


def ler(caminho: Path | str) -> Leitura:
    """Varre o PDF e propoe um recorte por questao."""
    caminho = Path(caminho)
    doc = pymupdf.open(caminho)
    try:
        leitura = Leitura(caminho=caminho, paginas=doc.page_count)
        layout = _layout(doc)
        fim = _ultima_pagina_com_texto(doc, layout)

        apoios_brutos: list[tuple[int, float, int, int, str]] = []
        constantes: list[tuple[int, float, str]] = []
        for indice in range(doc.page_count):
            for y0, _, texto, negrito in _linhas(doc[indice]):
                if not (layout.topo - 4 <= y0 < layout.rodape):
                    continue
                casamento = MARCADOR.match(texto)
                if casamento and negrito:
                    numero = int(casamento.group(1) + (casamento.group(2) or ""))
                    leitura.marcadores.append(
                        Marcador(numero, indice, y0, texto.strip()[:60])
                    )
                    continue
                apoio = APOIO.search(texto)
                if apoio and APOIO_GATILHO.search(texto):
                    apoios_brutos.append(
                        (indice, y0, int(apoio.group(1)), int(apoio.group(2)), texto.strip())
                    )
                elif CONSTANTES.match(texto) and negrito:
                    constantes.append((indice, y0, texto.strip()))

        leitura.marcadores = [
            _recuar_ate_o_topo_do_bloco(doc, m)
            for m in sorted(leitura.marcadores, key=lambda m: (m.pagina, m.y))
        ]
        if not leitura.marcadores:
            leitura.avisos.append("Nenhuma questão encontrada neste PDF.")
            return leitura

        for pagina_c, y_c, texto_c in constantes:
            adiante = [
                m for m in leitura.marcadores
                if (m.pagina, m.y) > (pagina_c, y_c)
            ]
            if adiante:
                apoios_brutos.append(
                    (pagina_c, y_c, adiante[0].numero, leitura.marcadores[-1].numero, texto_c)
                )

        leitura.apoios = _montar_apoios(apoios_brutos, leitura.marcadores, layout)
        leitura.recortes = _montar_recortes(leitura.marcadores, leitura.apoios, fim, layout)

        mobilia = _mobilia(doc)
        for recorte in leitura.recortes:
            recorte.regioes = _aparar(doc, recorte.regioes, mobilia, layout)
        for apoio in leitura.apoios:
            apoio.regioes = _aparar(doc, apoio.regioes, mobilia, layout)

        leitura.avisos.extend(_conferir(leitura))
        return leitura
    finally:
        doc.close()


def _recuar_ate_o_topo_do_bloco(doc, marcador: Marcador) -> Marcador:
    """Sobe o marcador ate o topo visual da primeira linha da questao.

    A matematica vem do OMML do Word em varias linhas de base: expoentes e
    numeradores ficam ACIMA da linha onde esta escrito "Questão 7.". Cortar na
    altura do marcador deixaria esses pedacos na questao anterior.
    """
    pagina = doc[marcador.pagina]
    topo = marcador.y

    caixas = [
        linha["bbox"]
        for bloco in pagina.get_text("dict")["blocks"]
        for linha in bloco.get("lines", [])
        if "".join(s["text"] for s in linha["spans"]).strip()
    ]
    # A barra de fracao e um desenho, nao texto: sem ela o fiapo da formula da
    # questao seguinte ficava pendurado no recorte da anterior.
    caixas += [d["rect"] for d in pagina.get_drawings()]

    for caixa in caixas:
        y0, y1 = caixa[1], caixa[3]
        if y0 < marcador.y and y1 > marcador.y - 4 and marcador.y - y0 < 22:
            topo = min(topo, y0)
    return Marcador(marcador.numero, marcador.pagina, topo, marcador.texto)


def _montar_apoios(brutos, marcadores, layout: Layout) -> list[BlocoApoio]:
    """O apoio vai do anuncio ate o primeiro marcador do intervalo que ele serve."""
    por_numero = {m.numero: m for m in marcadores}
    saida = []
    for pagina, y0, primeira, ultima, texto in brutos:
        alvo = por_numero.get(primeira)
        if alvo is None:
            continue
        if alvo.pagina == pagina:
            regioes = [Regiao(pagina, max(y0 - FOLGA, layout.topo), alvo.y - 2)]
        else:
            regioes = [Regiao(pagina, max(y0 - FOLGA, layout.topo), layout.rodape)]
            for meio in range(pagina + 1, alvo.pagina):
                regioes.append(Regiao(meio, layout.topo, layout.rodape))
            regioes.append(Regiao(alvo.pagina, layout.topo, alvo.y - 2))
        saida.append(BlocoApoio(primeira, ultima, regioes, texto[:120]))
    return saida


def _montar_recortes(marcadores, apoios, ultima_pagina, layout: Layout) -> list[Recorte]:
    recortes = []
    for indice, marcador in enumerate(marcadores):
        seguinte = marcadores[indice + 1] if indice + 1 < len(marcadores) else None
        inicio = max(marcador.y - FOLGA, layout.topo)

        if seguinte is None:
            regioes = [Regiao(marcador.pagina, inicio, layout.rodape)]
            for meio in range(marcador.pagina + 1, ultima_pagina + 1):
                regioes.append(Regiao(meio, layout.topo, layout.rodape))
        elif seguinte.pagina == marcador.pagina:
            regioes = [Regiao(marcador.pagina, inicio, seguinte.y - 2)]
        else:
            regioes = [Regiao(marcador.pagina, inicio, layout.rodape)]
            for meio in range(marcador.pagina + 1, seguinte.pagina):
                regioes.append(Regiao(meio, layout.topo, layout.rodape))
            if seguinte.y - 2 > layout.topo:
                regioes.append(Regiao(seguinte.pagina, layout.topo, seguinte.y - 2))

        # O apoio fica antes do marcador, entao nao entra na regiao da questao —
        # ele viaja junto como bloco separado.
        apoio = next((a for a in apoios if a.serve(marcador.numero)), None)
        recortes.append(
            Recorte(marcador.numero, [r for r in regioes if r.altura > 8], apoio)
        )
    return recortes


FOLGA_FIM_DE_PAGINA = 40.0   # o quanto sobrar no pe ja significa "acabou aqui"


def _aparar(doc, regioes: list[Regiao], mobilia: set, layout: Layout) -> list[Regiao]:
    """Encolhe cada regiao ate onde o conteudo termina de verdade.

    E descarta a continuacao na pagina seguinte quando a questao ja se encerrou com
    folga no pe da anterior: o que sobra no alto da proxima pagina costuma ser um
    expoente ou uma barra de fracao da questao seguinte, nao a continuacao desta.
    """
    saida = []
    for indice, regiao in enumerate(regioes):
        if regiao.pagina >= doc.page_count:
            continue
        fim = _fim_do_conteudo(doc[regiao.pagina], regiao.y0, regiao.y1, mobilia, layout.rodape)
        if fim - regiao.y0 <= 8:
            continue
        if indice > 0 and saida:
            anterior = saida[-1]
            terminou_antes = anterior.y1 < layout.rodape - FOLGA_FIM_DE_PAGINA
            if terminou_antes:
                break
        saida.append(Regiao(regiao.pagina, regiao.y0, fim))
    return saida or regioes[:1]


def _conferir(leitura: Leitura) -> list[str]:
    """Avisos para a tela de revisao. Nada aqui impede a importacao."""
    avisos = []
    numeros = leitura.numeros

    if len(set(numeros)) != len(numeros):
        repetidos = sorted({n for n in numeros if numeros.count(n) > 1})
        avisos.append(f"Questão repetida no PDF: {', '.join(map(str, repetidos))}.")

    esperados = set(range(1, max(numeros) + 1))
    faltando = sorted(esperados - set(numeros))
    if faltando:
        avisos.append(f"Não encontrei a(s) questão(ões) {', '.join(map(str, faltando))}.")

    for recorte in leitura.recortes:
        if recorte.atravessa_pagina:
            avisos.append(
                f"A questão {recorte.numero} atravessa página — confira se o recorte pegou tudo."
            )
        elif recorte.altura_total < 40:
            avisos.append(f"A questão {recorte.numero} ficou muito curta ({recorte.altura_total:.0f}pt).")

    for apoio in leitura.apoios:
        avisos.append(
            f"As questões {apoio.primeira} a {apoio.ultima} dividem um texto de apoio."
        )
    return avisos
